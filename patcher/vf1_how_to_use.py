"""The patcher window's "?" guides (how_to_use.json), in the style of the Virtual Villagers Fun Patcher's.

Every patch and every button, tool and setting has one short plain guide:
what it does, how to use it, and what to watch out for. The guides are data,
kept beside this file and keyed by the ids the patcher already uses -- a patch
by its setting id, everything else by a control key. They are not put into
the patch manifest: a guide is presentation text that must never change what
a patch does. tests/test_how_to_use.py refuses a manifest patch or a window
control without a guide, so a new feature cannot ship without one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GUIDES_PATH = Path(__file__).resolve().parent / "how_to_use.json"

# Guides stay short: "brief, simple to understand".
MAX_LINES = 8
MAX_LINE_CHARS = 200
MAX_GUIDE_CHARS = 1000


@dataclass(frozen=True)
class Guide:
    title: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(self.lines)


def patch_key(patch_id: str) -> str:
    return f"patch:{patch_id}"


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(GUIDES_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def guide_lines() -> dict[str, tuple[str, ...]]:
    """Every guide by key: ``patch:<id>`` or a control key. A patch listed twice is an error."""
    data = _load()
    result: dict[str, tuple[str, ...]] = {}
    for entry in data["patches"]:
        for patch_id in entry["ids"]:
            key = patch_key(patch_id)
            if key in result:
                raise ValueError(f"{patch_id} has more than one guide in {GUIDES_PATH.name}")
            result[key] = tuple(entry["guide"])
    for control, entry in data["controls"].items():
        result[control] = tuple(entry["guide"])
    return result


def control_title(key: str) -> str:
    return _load()["controls"][key]["title"]


def guide(key: str, title: str | None = None) -> Guide:
    """The guide for ``key``; KeyError when there is none.

    ``title`` names the window: a patch passes its own display name, a control
    uses the title stored with its guide.
    """
    lines = guide_lines()[key]
    if title is None:
        title = control_title(key)
    return Guide(title=title, lines=lines)
