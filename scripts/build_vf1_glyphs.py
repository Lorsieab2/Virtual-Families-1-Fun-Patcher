"""Builds patcher\\payload\\UnicodeText: the patcher-made letters for Virtual Families 1's fonts (Render Unicode
with In-Game Fonts and the Game Text tool).

    python scripts/build_vf1_glyphs.py [--game "<vanilla Virtual Families folder>"] [--only NAME ...]

The game folder (VF1_VANILLA_DIR by default) is only read. For every font:

* the style the missing letters are drawn in: the face and weight (Segoe UI, regular for SegoeUi*, bold for
  SegoeUiBold*; the closest Windows face for the other sheets), the em size whose letters differ least from
  the game's own A..Z a..z 0..9 pixel by pixel, the baseline (the bottom of the game's "H") and the
  coverage map ("lut", a gamma fitted to the same letters);
* for the game's four fonts, every letter of vf1_glyph_maker.shipped_letters() that the style can make,
  composed from the game's own pixels where it can be (vf1_glyph_maker), into <font>.png (bands of the font's
  height, at most 2048 pixels wide) and <font>.txt;
* for the ten unused sheets, the glyph boxes found from the sheet (metrics NOT from the game: the exe has
  none): the 190 boxes, in the game's order, whose edges fall on the emptiest columns while keeping each
  box near the width a game font gives that letter, every edge in a gap moved to the gap's middle.

Needs Windows (GDI), numpy and Pillow (development only; the patcher itself needs neither).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import vf1_game_fonts as gf          # noqa: E402
import vf1_glyph_gdi as gdi          # noqa: E402
import vf1_glyph_maker as gm         # noqa: E402
import vf1_picture_image as pi       # noqa: E402

OUT = ROOT / "patcher" / "payload" / "UnicodeText"
FIT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
ATLAS_WIDTH = 2048
# Faces tried for each sheet (face, weight).
CANDIDATES = {
    "SegoeUi": [("Segoe UI", 400)],
    "SegoeUiBold": [("Segoe UI", 700)],
    "AmericanTypewriter": [("Courier New", 400), ("Courier New", 700), ("Cambria", 400)],
    "SFCartoonistHandBold": [("Comic Sans MS", 700), ("Segoe Print", 700)],
    "ldwBurweed": [("Segoe Print", 700), ("Comic Sans MS", 700)],
    "ldwarialbold": [("Arial", 700)],
}


def candidates(name: str):
    for prefix in sorted(CANDIDATES, key=len, reverse=True):
        if name.startswith(prefix):
            return CANDIDATES[prefix]
    return [("Segoe UI", 400)]


def alpha_array(img: pi.Image) -> np.ndarray:
    return np.frombuffer(bytes(img.data[3::4]), dtype=np.uint8).reshape(img.height, img.width).astype(int)


def fit_style(font: gf.GameFont) -> gf.Style:
    h = font.height
    hbox = alpha_array(font.game_glyph(ord("H")).image)
    ys = np.nonzero(hbox.max(axis=1))[0]
    baseline = int(ys[-1]) + 1
    best = None
    for face, weight in candidates(font.name):
        for em in range(max(6, int(h * 0.45)), int(h * 1.25) + 1):
            r = gdi.Renderer(face, weight, em, baseline, h, fallbacks=())
            if r.face_for("A") is None:
                r.close()
                break
            err = 0.0
            for ch in FIT_LETTERS:
                g = font.game_glyph(ord(ch))
                img, _ = r.draw(ch)
                ga, ra = alpha_array(g.image), alpha_array(img)
                w = min(ga.shape[1], ra.shape[1])
                err += np.abs(ga[:, :w] - ra[:, :w]).sum() / 255 + 3 * abs(ga.shape[1] - ra.shape[1]) * h
            r.close()
            if best is None or err < best[0]:
                best = (err, face, weight, em)
    _, face, weight, em = best
    # the coverage map
    r = gdi.Renderer(face, weight, em, baseline, h, fallbacks=())
    xs, ys2 = [], []
    for ch in FIT_LETTERS:
        g = font.game_glyph(ord(ch))
        img, _ = r.draw(ch)
        ga, ra = alpha_array(g.image), alpha_array(img)
        if ga.shape == ra.shape:
            xs.append(ra.ravel())
            ys2.append(ga.ravel())
    r.close()
    gamma = 1.0
    if xs:
        x, y = np.concatenate(xs), np.concatenate(ys2)
        errs = []
        for gmv in np.arange(0.6, 3.01, 0.02):
            lut = np.round(255 * (np.arange(256) / 255) ** gmv).astype(int)
            errs.append((np.abs(lut[x] - y).mean(), round(float(gmv), 2)))
        gamma = min(errs)[1]
    gamma = min(2.6, max(1.8, gamma))      # a face unlike the sheet fits no gamma well
    lut = tuple(int(round(255 * (v / 255) ** gamma)) for v in range(256))
    print(f"  {font.name}: {face} {weight}, em {em}, baseline {baseline}, gamma {gamma}")
    return gf.Style(face, weight, em, baseline, lut)


# --------------------------------------------------------------------------- unused sheets' boxes
def reference_widths(fonts: gf.Fonts, bold: bool) -> list[int]:
    ref = fonts.font("SegoeUiBold24" if bold else "SegoeUi33")
    return [r[3] - r[1] for r in ref.rows]


def derive_boxes(sheet: pi.Image, ref: list[int], wpen: float = 4.0) -> list[int]:
    a = alpha_array(sheet).astype(np.float64) / 255.0
    w_total = a.shape[1]
    col = a.sum(axis=0)
    col = col / (col.max() or 1)
    n = len(ref)
    pri = np.array(ref, dtype=np.float64) * (w_total / sum(ref))
    bc = np.zeros(w_total + 1)
    bc[1:w_total] = col[:-1] + col[1:]
    inf = 1e18
    cost = np.full((n + 1, w_total + 1), inf)
    back = np.zeros((n + 1, w_total + 1), dtype=np.int32)
    cost[0, 0] = 0
    for k in range(1, n + 1):
        p = pri[k - 1]
        prev = cost[k - 1]
        for wdt in range(max(1, int(p * 0.4)), int(p * 2.2) + 4):
            if wdt > w_total:
                break
            pen = wpen * ((wdt - p) / max(p, 3)) ** 2
            cand = prev[:w_total + 1 - wdt] + pen + bc[wdt:w_total + 1]
            tgt = cost[k, wdt:]
            better = cand < tgt
            tgt[better] = cand[better]
            back[k, wdt:][better] = wdt
    bounds = [w_total]
    c = w_total
    for k in range(n, 0, -1):
        c -= back[k, c]
        bounds.append(int(c))
    bounds.reverse()
    ink = (a > 0).any(axis=0)

    def gap(c):
        if (c - 1 >= 0 and ink[c - 1]) and (c < w_total and ink[c]):
            return None
        lo = c
        while lo - 1 >= 0 and not ink[lo - 1]:
            lo -= 1
        hi = c
        while hi < w_total and not ink[hi]:
            hi += 1
        return lo, hi

    gaps = [gap(c) for c in bounds]
    out = [bounds[0]]
    for k in range(1, len(bounds) - 1):
        g = gaps[k]
        # an edge alone in its gap goes to the gap's middle; edges sharing a gap (a blank letter, the space,
        # between them) stay where they were found
        if g is None or gaps[k - 1] == g or gaps[k + 1] == g:
            out.append(bounds[k])
        else:
            out.append((g[0] + g[1] + 1) // 2)
    out.append(bounds[-1])
    return out


# --------------------------------------------------------------------------- writing
def glyph_text(font: gf.GameFont, style: gf.Style, boxes: list[tuple[str, int, int, int, str]],
               metrics: list[tuple[int, int, int]] | None) -> str:
    lines = [
        "vf1-glyphs 1",
        "# Made by scripts/build_vf1_glyphs.py (Render Unicode with In-Game Fonts). Not the game's own art.",
    ]
    if metrics:
        lines.append("# The glyph boxes (m lines) were found from the sheet: metrics not from the game.")
    lines += [
        f"font {font.name}",
        f"height {font.height}",
        f"baseline {style.baseline}",
        f"face {style.face}",
        f"weight {style.weight}",
        f"em {style.em}",
        "lut " + " ".join(str(v) for v in style.lut),
    ]
    for code, left, right in metrics or ():
        lines.append(f"m {code:X} {left} {right}")
    for letter, x, y, w, how in boxes:
        lines.append(f"g {'+'.join(f'{ord(c):X}' for c in letter)} {x} {y} {w} {how}")
    return "\n".join(lines) + "\n"


def build_font(fonts: gf.Fonts, name: str, out: Path) -> None:
    font = fonts.font(name)
    style = fit_style(font)
    font.glyphs = gf.GlyphFile(style, None)
    renderer = gdi.Renderer(style.face, style.weight, style.em, style.baseline, font.height)

    def game(letter: str):
        if len(letter) == 1 and font.has_native(letter):
            return font.game_glyph(ord(letter)).image
        return None

    def draw(letter: str):
        img, face = renderer.draw(letter)
        if not face:
            return None
        img.data[3::4] = bytes(style.lut[a] for a in img.data[3::4])
        return img

    xb = gm._ink_box(gm._alpha(font.game_glyph(ord("x")).image))
    hb = gm._ink_box(gm._alpha(font.game_glyph(ord("H")).image))
    maker = gm.Maker(font.height, game, draw, xb[1], hb[1])
    made = []
    for letter in gm.shipped_letters():
        m = maker.make(letter)
        if m is not None and m.image.height == font.height:
            made.append((letter, m))
    renderer.close()
    # bands
    boxes = []
    x = y = 0
    band = font.height
    for letter, m in made:
        w = m.image.width
        if x + w > ATLAS_WIDTH:
            x, y = 0, y + band
        boxes.append((letter, x, y, w, m.how.replace(" ", "-")))
        x += w
    atlas = pi.Image(ATLAS_WIDTH, y + band)
    for (letter, bx, by, w, _), (_, m) in zip(boxes, made):
        atlas.data  # noqa: B018
        for yy in range(m.image.height):
            s = yy * w * 4
            d = ((by + yy) * atlas.width + bx) * 4
            atlas.data[d:d + w * 4] = m.image.data[s:s + w * 4]
    (out / f"{name}.png").write_bytes(atlas.to_png())
    (out / f"{name}.txt").write_text(glyph_text(font, style, boxes, None), encoding="utf-8", newline="\n")
    counts = {}
    for b in boxes:
        counts[b[4]] = counts.get(b[4], 0) + 1
    print(f"  {name}: {len(boxes)} letters {counts}")


def build_unused(fonts: gf.Fonts, name: str, out: Path) -> None:
    sheet = pi.decode_png((fonts.game_dir / "Images" / f"{name}.png").read_bytes())
    bold = "Bold" in name or name in ("ldwarialbold",)
    bounds = derive_boxes(sheet, reference_widths(fonts, bold))
    metrics = [(code, bounds[k], bounds[k + 1]) for k, code in enumerate(gf.SHEET_ORDER)]
    rows = [(c if c < 0x80 else c - 0x100, l, 0, r, sheet.height) for c, l, r in metrics]
    font = gf.GameFont(name, sheet, rows, 0, in_game=False, metrics_from_game=False, glyphs=None)
    style = fit_style(font)
    (out / f"{name}.txt").write_text(glyph_text(font, style, [], metrics), encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--game", default=os.environ.get("VF1_VANILLA_DIR", ""))
    p.add_argument("--only", nargs="*")
    args = p.parse_args(argv)
    if not args.game:
        p.error("give --game or set VF1_VANILLA_DIR")
    OUT.mkdir(parents=True, exist_ok=True)
    fonts = gf.Fonts(Path(args.game), glyph_dir=OUT)
    for name in gf.GAME_FONTS:
        if not args.only or name in args.only:
            build_font(fonts, name, OUT)
    for name in gf.UNUSED_FONTS:
        if not args.only or name in args.only:
            build_unused(fonts, name, OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
