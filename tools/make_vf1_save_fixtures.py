"""Make a test fixture from a COPY of a real Virtual Families 1 save (read only).

    python tools/make_vf1_save_fixtures.py <copied save .ldw> <fixture name>

Save files are never committed (.gitignore: *.ldw). A fixture keeps only what patcher/vf1_save.py parses
-- the header and the ranges listed in KEEP -- as zlib + base64 in tests/fixtures/vf1_saves/<name>.json;
everything else (achievements, collectables, inventory, pets, tutorial tips, the villagers' AI blocks) is
left out and rebuilt as zeros by tests/test_vf1_save.py. No path is written into the fixture.
"""
from __future__ import annotations

import base64
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
import vf1_save as vs  # noqa: E402

KEEP = [  # (gs offset, length)
    (vs.GS_FAMILY_TREE, vs.FAMILY_RECORDS * vs.FAMILY_RECORD),
    (vs.GS_FOOD, 4), (vs.GS_STATS, 0x34), (vs.GS_GAME_TIME, 0x14), (vs.GS_MONEY, 8),
    (vs.GS_PENDING_BABIES, vs.GS_SAVED_END - vs.GS_PENDING_BABIES),
] + [(vs.GS_VILLAGERS + k * vs.VILLAGER_RECORD, 0x168) for k in range(vs.VILLAGER_SLOTS)]


def make(data: bytes) -> dict:
    header = vs.parse_header(data)
    vs.parse_save(data)  # refuse anything that is not a slot save
    payload = data[header.size:]
    sections = {}
    for gs, n in KEEP:
        o = gs - vs.GS_BASE
        sections[f"0x{gs:X}"] = base64.b64encode(zlib.compress(payload[o:o + n], 9)).decode()
    return {"header": data[:header.size].hex(), "sections": sections}


def rebuild(fixture: dict) -> bytes:
    payload = bytearray(vs.PAYLOAD_SIZE)
    for gs, blob in fixture["sections"].items():
        raw = zlib.decompress(base64.b64decode(blob))
        o = int(gs, 16) - vs.GS_BASE
        payload[o:o + len(raw)] = raw
    return bytes.fromhex(fixture["header"]) + bytes(payload)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = ROOT / "tests" / "fixtures" / "vf1_saves" / f"{argv[1]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(make(Path(argv[0]).read_bytes()), indent=1) + "\n", encoding="utf-8")
    print(out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
