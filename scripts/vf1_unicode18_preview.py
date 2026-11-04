"""A preview sheet of Unicode 18.0 in Virtual Families 1's four fonts, drawn exactly as Render Unicode with In-Game Fonts
draws it (vf1_game_fonts: the game's own letters, the patcher-made ones, the ones Windows draws and, last, the open
fonts the patcher ships): for each font, the game's own letters beside letters of scripts and emoji newer than
Python's and Windows' Unicode data, Tangut, Early Dynastic Cuneiform and a private-use character.

Usage:  python scripts/vf1_unicode18_preview.py --game "<original Virtual Families folder>" --out preview.png
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import vf1_game_fonts as gf  # noqa: E402
import vf1_picture_image as pi  # noqa: E402
import vf1_unicode18 as u18  # noqa: E402

BACKGROUND = (24, 40, 74, 255)


def newer(count: int, emoji: bool) -> str:
    """`count` letters (or emoji) assigned in Unicode 18.0 that this Python's unicodedata (16.0) does not know, from
    as many blocks as there are."""
    marks = {cp for a, b in u18.EXTENDER_MARKS for cp in range(a, b + 1)}
    pictures = {cp for a, b in u18.EMOJI_PRESENTATION for cp in range(a, b + 1)}
    out, blocks = [], set()
    for a, b in u18.ASSIGNED:
        for cp in range(a, b + 1):
            if unicodedata.category(chr(cp)) != "Cn" or cp in marks or 0xE000 <= cp <= 0xF8FF or cp >= 0xF0000:
                continue
            if (cp in pictures) != emoji or (cp >> 8) in blocks:
                continue
            blocks.add(cp >> 8)
            out.append(chr(cp))
            if len(out) == count:
                return "".join(out)
    return "".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    fonts = gf.Fonts(a.game)
    rows = [
        ("The game's letters", "Aa Bb Éé Zoë 123 &?!"),
        ("New letters (Unicode 17-18)", newer(18, False)),
        ("New emoji (Unicode 17-18)", newer(10, True)),
        ("Tangut, cuneiform, private use", "\U00017000\U00017001\U00018B00 \U00012480\U00012481 "),
    ]
    pieces = []
    label_font = fonts.font("SegoeUiBold17")
    for name in ("SegoeUiBold18", "SegoeUiBold17", "SegoeUiBold24", "SegoeUi33"):
        f = fonts.font(name)
        pieces.append(label_font.render(name, 0xFFC0E0FF))
        for label, text in rows:
            line = f.render(text + "   ", 0xFFFFFFFF)
            tag = label_font.render(label, 0xFFA0A0A0)
            row = pi.Image(tag.width + 16 + line.width, max(tag.height, line.height))
            row.draw(tag, 0, 0)
            row.draw(line, tag.width + 16, 0)
            pieces.append(row)
    width = max(p.width for p in pieces) + 32
    height = sum(p.height + 6 for p in pieces) + 32
    sheet = pi.Image(width, height)
    sheet.data[:] = bytes(BACKGROUND) * (width * height)
    y = 16
    for p in pieces:
        sheet.draw(p, 16, y)
        y += p.height + 6
    a.out.write_bytes(pi.encode_png(sheet))
    print(a.out, sheet.width, sheet.height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
