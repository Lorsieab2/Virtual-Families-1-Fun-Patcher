"""Writes native/vf1text/extenders.inc from patcher/vf1_text.py's EXTENDER_RANGES, so vf1text.dll splits text into
whole characters exactly as the patcher's readers do (Render Unicode with In-Game Fonts), and
native/vf1text/emoji.inc from patcher/vf1_emoji.py's EMOJI_PRESENTATION_RANGES, so the DLLs pick the same colour
emoji as the patcher's tools.

    python scripts/build_vf1_text_tables.py [--check]

--check only says whether the files are up to date (tests/test_vf1_text.py runs it).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import vf1_emoji  # noqa: E402
import vf1_text  # noqa: E402

TARGETS = (
    (ROOT / "native" / "vf1text" / "extenders.inc", vf1_text.cluster_table_c),
    (ROOT / "native" / "vf1text" / "emoji.inc", vf1_emoji.emoji_table_c),
)


def main(argv: list[str]) -> int:
    for target, make in TARGETS:
        text = make()
        if "--check" in argv:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != text:
                print(f"{target} is out of date: run scripts/build_vf1_text_tables.py")
                return 1
            continue
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
