"""Writes native/vf1text/extenders.inc from patcher/vf1_text.py's EXTENDER_RANGES, so vf1text.dll splits text into
whole characters exactly as the patcher's readers do (Render Unicode with In-Game Fonts).

    python scripts/build_vf1_text_tables.py [--check]

--check only says whether the file is up to date (tests/test_vf1_text.py runs it).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import vf1_text  # noqa: E402

TARGET = ROOT / "native" / "vf1text" / "extenders.inc"


def main(argv: list[str]) -> int:
    text = vf1_text.cluster_table_c()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} is out of date: run scripts/build_vf1_text_tables.py")
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
