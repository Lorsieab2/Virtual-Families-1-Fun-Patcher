"""Skin Tones: the recolour, exactly as the Virtual Villagers Fun Patcher makes its tones, and the tone preview.

THE RECOLOUR (the owner, 2026-11-28: VF1's skin tones look exactly like the Virtual Villagers patcher's). This is that
patcher's method (its src/vv_skin_tone_art.py shade(), recolour(), tone_scales() and oklch_to_rgb(), its
src/vv_skin_tones.py TONE_TABLE), copied number for number; vf1skin.dll does the same in C (native/vf1skin/vf1skin.cpp
MakeRow) and tests/test_skin_tone_draw.py holds the DLL's pixels to this file's, on the real sheets and masks:

  * A ROW is one row of cells of a sheet (one head, one outfit in every pose).  Of a row's skin pixels (the mask, and
    not fully transparent), the OKLab lightness of each, counted once per pixel, gives the row's middle skin (the 50th
    percentile) and how far its skin reaches below and above it (the 2nd and 98th).
  * A skin pixel takes the tone's hue and chroma in OKLCh; its lightness is the tone's plus the pixel's own offset from
    the row's middle, at SHADING strength, so the art's shading shows (tone_scales: less where the floor L_FLOOR or the
    ceiling L_CEIL is in the way, and GIVE more on the other side).  Shadows get up to SHADOW_CHROMA more chroma.
    Outside sRGB the hue always stays; chroma gives way first, never below CHROMA_FLOOR of the tone's own, and then
    lightness moves toward the tone's.
  * Alpha and every pixel outside the mask are left exactly as they are.

THE PREVIEW (preview()): a female and a male adult standing, facing you (the actions sheet's column 14, the head
looking straight out), in each of the ten tones, drawn from the player's own game pictures at run time with the
masks the patcher ships.  Nothing of the game's art is in the patcher.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

import vf1_picture_image as pi
import vf1_skin_tones as tones

MASKS = Path(__file__).resolve().parent / "payload" / "SkinMasks"

L_FLOOR, L_CEIL = 0.14, 0.985
GIVE, SHADING, CHROMA_FLOOR, SHADOW_CHROMA = 0.3, 0.65, 0.78, 0.22
PERCENTILES = (2, 50, 98)


# ---- colour ---------------------------------------------------------------------------------------------------------

_LINEAR = [c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in range(256)]


def oklch(text: str):
    """(lightness, chroma, hue in degrees) of a "#rrggbb" colour in OKLCh."""
    lin = []
    for i in (1, 3, 5):
        c = int(text[i:i + 2], 16) / 255
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(A, B), math.degrees(math.atan2(B, A))


# (name, hex, OKLab lightness, chroma, hue in degrees) of each tone's lit mid-skin, light to dark.
TONE_TABLE = tuple((name, text) + oklch(text) for name, text in zip(tones.TONE_NAMES, tones.TONE_COLOURS))


def lightness(r: int, g: int, b: int) -> float:
    """OKLab lightness of an 8-bit colour."""
    lr, lg, lb = _LINEAR[r], _LINEAR[g], _LINEAR[b]
    l_ = (0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb) ** (1 / 3)
    m_ = (0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb) ** (1 / 3)
    s_ = (0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb) ** (1 / 3)
    return 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_


def _linear_rgb(L: float, c: float, cos_h: float, sin_h: float):
    a, b = c * cos_h, c * sin_h
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def _fits(L: float, c: float, cos_h: float, sin_h: float) -> bool:
    return all(-1e-4 <= v <= 1 + 1e-4 for v in _linear_rgb(L, c, cos_h, sin_h))


def oklch_to_rgb(L: float, c: float, hue: float, floor: float, toward: float):
    """The 8-bit sRGB colour of an OKLCh colour.  Outside sRGB it keeps its hue always; it gives up chroma first, never
    below `floor`, and where even that does not fit its lightness moves toward `toward`."""
    cos_h, sin_h = math.cos(math.radians(hue)), math.sin(math.radians(hue))
    floor = min(floor, c)
    if not _fits(L, floor, cos_h, sin_h):
        lo, hi = L, toward
        for _ in range(14):
            mid = (lo + hi) / 2
            if _fits(mid, floor, cos_h, sin_h):
                hi = mid
            else:
                lo = mid
        L = hi
    if not _fits(L, c, cos_h, sin_h):
        lo, hi = floor, c
        for _ in range(14):
            mid = (lo + hi) / 2
            if _fits(L, mid, cos_h, sin_h):
                lo = mid
            else:
                hi = mid
        c = lo
    out = []
    for v in _linear_rgb(L, c, cos_h, sin_h):
        v = min(max(v, 0.0), 1.0)
        v = v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(int(round(v * 255)))
    return tuple(out)


# ---- replace --------------------------------------------------------------------------------------------------------

def percentile(ordered, q):
    """The q-th percentile of an ordered list, between neighbours in a straight line."""
    at = (len(ordered) - 1) * q / 100
    lo = int(math.floor(at))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo)


def tone_scales(L, down, up):
    """How much of the art's shading below and above a row's middle skin a tone of lightness L keeps: 1, or less where
    the floor or the ceiling is in the way -- and then a little more on the other side."""
    s_down = max(min(1.0, (L - L_FLOOR) / max(down, 1e-6)), 0.0)
    s_up = max(min(1.0, (L_CEIL - L) / max(up, 1e-6)), 0.0)
    more_up = min(1 + GIVE * (1 - s_down), (L_CEIL - L) / max(up, 1e-6))
    more_down = min(1 + GIVE * (1 - s_up), (L - L_FLOOR) / max(down, 1e-6))
    return (more_down if s_up < 1 else s_down), (more_up if s_down < 1 else s_up)


def shade(offset, tone, down, up):
    """The 8-bit colour of tone `tone` (a TONE_TABLE row) at lightness `offset` from a row's middle skin, the row's
    skin reaching `down` below and `up` above it."""
    _name, _hex, L, c, hue = tone
    offset, down, up = offset * SHADING, down * SHADING, up * SHADING
    s_down, s_up = tone_scales(L, down, up)
    out_L = min(max(L + (offset * s_down if offset < 0 else offset * s_up), L_FLOOR), L_CEIL)
    depth = min(max(-offset / max(down, 1e-6), 0.0), 1.0)
    return oklch_to_rgb(out_L, c * (1 + SHADOW_CHROMA * depth), hue, CHROMA_FLOOR * c, L)


class Band:
    """One row of cells' skin: each skin pixel's colour, each colour's lightness, and the row's middle skin and reach
    (the 2nd, 50th and 98th percentiles, every skin pixel counted)."""

    def __init__(self, data: bytes, members) -> None:
        self.colours = {i: bytes(data[4 * i:4 * i + 3]) for i in members}
        self.light = {rgb: lightness(*rgb) for rgb in set(self.colours.values())}
        if self.colours:
            ordered = sorted(self.light[rgb] for rgb in self.colours.values())
            self.lo, self.mid, self.hi = (percentile(ordered, q) for q in PERCENTILES)

    def toned(self, tone: int) -> dict:
        """{pixel number: (r, g, b)} of every skin pixel in tone `tone` (1..10)."""
        if not self.colours:
            return {}
        made = {rgb: shade(L - self.mid, TONE_TABLE[tone - 1], self.mid - self.lo, self.hi - self.mid)
                for rgb, L in self.light.items()}
        return {i: made[rgb] for i, rgb in self.colours.items()}


def recolour_band(data: bytes, members, tone: int) -> dict:
    """{pixel number: (r, g, b)} for the skin pixels `members` (pixel numbers into RGBA `data`, one row of cells) in
    tone `tone` (1..10): the Virtual Villagers patcher's recolour of one row."""
    return Band(data, members).toned(tone)


# ---- the masks the patcher ships -------------------------------------------------------------------------------------

def read_mask(data: bytes) -> tuple[int, int, list[bytes]]:
    """(width, height, packed rows: the leftmost pixel in the top bit, 1 = skin) of a shipped 1-bit mask picture."""
    if data[:8] != pi.PNG_MAGIC or data[12:16] != b"IHDR":
        raise pi.PictureError("a skin mask is not a PNG picture")
    w, h = struct.unpack(">II", data[16:24])
    if data[24:29] != bytes([1, 0, 0, 0, 0]):
        raise pi.PictureError("a skin mask is not a black and white picture")
    pos, idat = 8, b""
    while pos + 8 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        if data[pos + 4:pos + 8] == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = (w + 7) // 8
    rows = [bytes(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)]) for y in range(h)]
    if any(raw[y * (stride + 1)] for y in range(h)):
        raise pi.PictureError("a skin mask is not one the patcher made")
    return w, h, rows


def mask_info() -> dict[str, dict]:
    """masks.json: each sheet's size and the SHA-256 of the vanilla file its mask was made from."""
    data = json.loads((MASKS / "masks.json").read_text(encoding="utf-8"))
    return {m["sheet"]: m for m in data["masks"]}


def band_of(sheet: pi.Image, mask_rows: list[bytes], top: int, height: int) -> tuple[pi.Image, Band]:
    """Rows top..top+height of `sheet` (one row of cells), and their skin."""
    band = sheet.sub(0, top, sheet.width, height)
    w = sheet.width
    members = []
    for y in range(height):
        bits = mask_rows[top + y]
        for x in range(w):
            if bits[x >> 3] >> (7 - (x & 7)) & 1 and band.data[4 * (y * w + x) + 3]:
                members.append(y * w + x)
    return band, Band(band.data, members)


def tone_band(band: pi.Image, skin: Band, tone: int) -> pi.Image:
    """A copy of `band` with its skin in `tone`, everything else (and all alpha) as it is."""
    out = band.copy()
    for i, rgb in skin.toned(tone).items():
        out.data[4 * i:4 * i + 3] = bytes(rgb)
    return out


def toned_band(sheet: pi.Image, mask_rows: list[bytes], top: int, height: int, tone: int) -> pi.Image:
    """Rows top..top+height of `sheet` (one row of cells) with the skin in `tone`, everything else as it is."""
    return tone_band(*band_of(sheet, mask_rows, top, height), tone)


# ---- the preview ----------------------------------------------------------------------------------------------------

PREVIEW_PEOPLE = ((True, 7, 12), (False, 7, 12))     # (female, head picture, outfit picture): a woman, then a man
PREVIEW_AGE = 600                                   # 30 years: a grown-up, drawn at full size
PREVIEW_GAP = 6


class PreviewError(pi.PictureError):
    """The preview cannot be drawn, in words for the player."""


def preview(folder: Path) -> pi.Image:
    """A woman (top row) and a man (bottom row), standing and facing you as in Change Appearance's picture, in tones
    S1..S10 from left to right, drawn from the game folder's own pictures with the shipped masks."""
    import vf1_people_pictures as pp
    art = pp.Art(folder, "game")
    problem = art.problem()
    if problem:
        raise PreviewError(problem)
    info = mask_info()
    masks: dict[str, list[bytes]] = {}

    def mask(name: str) -> list[bytes]:
        if name not in masks:
            entry = info.get(name)
            path = art.path(name)
            if entry is None or path is None:
                raise PreviewError(f"Images\\{name} has no skin mask.")
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sheet_sha256"]:
                raise PreviewError(f"Images\\{name} is not the game's own picture, so Skin Tones draws it as it is "
                                   "and there is no preview.")
            w, h, rows = read_mask((MASKS / name).read_bytes())
            if (w, h) != (entry["width"], entry["height"]):
                raise PreviewError(f"The skin mask for Images\\{name} does not fit it.")
            masks[name] = rows
        return masks[name]

    pictures: list[list[pi.Image]] = []
    for female, head, body in PREVIEW_PEOPLE:
        person = pp.Person(female=female, age=PREVIEW_AGE, head=head, body=body)
        view = pp.HouseView(pose=pp.STANDING_POSE, head_turn=pp.FRONT_HEAD, shadow=False)
        plan = pp.house_plan(art, person, view)
        # only the cell drawn is needed, but the row's skin (every cell of it) sets the shading, as in the game
        bands = [band_of(art.image(call.file), mask(call.file), call.rect[1], call.rect[3] - call.rect[1])
                 for call in plan]
        row_pictures = []
        for tone in range(1, tones.TONE_COUNT + 1):
            drawn = []
            for call, (band, skin) in zip(plan, bands):
                x0, y0, x1, y1 = call.rect
                drawn.append((call, pi.game_layer(tone_band(band, skin, tone), (x0, 0, x1, y1 - y0), call.scale,
                                                  call.alpha)))
            left = min(c.x for c, _p in drawn)
            top = min(c.y for c, _p in drawn)
            right = max(c.x + p.width for c, p in drawn)
            bottom = max(c.y + p.height for c, p in drawn)
            canvas = pi.Image(right - left, bottom - top)
            for call, piece in drawn:
                canvas.draw(piece, call.x - left, call.y - top)
            row_pictures.append(canvas.cropped(1))
        pictures.append(row_pictures)
    cell_w = max(p.width for row in pictures for p in row)
    cell_h = max(p.height for row in pictures for p in row)
    out = pi.Image(tones.TONE_COUNT * (cell_w + PREVIEW_GAP) - PREVIEW_GAP,
                   len(pictures) * (cell_h + PREVIEW_GAP) - PREVIEW_GAP)
    for r, row in enumerate(pictures):
        for k, p in enumerate(row):
            out.draw(p, k * (cell_w + PREVIEW_GAP) + (cell_w - p.width) // 2,
                     r * (cell_h + PREVIEW_GAP) + (cell_h - p.height))
    return out
