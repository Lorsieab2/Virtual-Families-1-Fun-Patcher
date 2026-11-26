"""Skin Tones (vf1skin.dll): the tones, the inheritance rule and the per-save file, as the patcher's Python reads them.

One place for what the patcher must agree on with native/vf1skin/vf1skin.cpp (tests/test_skin_tones.py holds the two
together):

THE TONES. 1..10, light to dark: the owner's ten (2026-11-26), the Virtual Villagers patcher's names and colours. 15 is
Default (the game's own skin, chosen in Change Appearance); 0 is "none yet" (drawn as Default too).

THE FILE. "<save folder>\\Virtual Families 1 Patcher Data\\Skin Tones\\<save file>.dat", one per save FILE, in the Up to
28 Children file's layout (vf1kids.cpp): the tag "VF1SKIN\\0", version 1, "VF1V101\\0", the file's size, the FNV-1a 64
and size of the save it was written with, the generations, parent 1's slot and sex, the entry count, the entries
(ENTRY bytes each) and the FNV-1a 64 of everything before it. Copy, Move and Delete Player Slot, Rename Family, Back Up
Saves and Game Speed carry it and re-match it to a save they rewrite (vf1_genealogy.sidecar_key / children_rekeys).

One entry: the villager slot (-1 when they are not in the house), sex, the stored name (25 bytes and a NUL), the tone
(the Virtual Villagers patcher's value byte: 0 none, 1..10, 15 Default), the birth tone ("Reset to birth tone" puts it
back), head and body as last seen, two Family Tree places (generation 0: none) and a person number (a copy the game
makes of someone shares it).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

TONE_NAMES = ("Porcelain", "Fair", "Light golden", "Light olive", "Copper", "Warm brown", "Medium brown", "Deep brown",
              "Dark", "Ebony")
TONE_COLOURS = ("#fbe3d7", "#f0ccaa", "#e2b88c", "#cea878", "#cc8a5a", "#b0784e", "#92623e", "#724c32", "#523423",
                "#322017")
TONE_COUNT = len(TONE_NAMES)
TONE_NONE = 0
TONE_DEFAULT = 15
DEFAULT_NAME = "Default"
LOG_WORD = "skin tone"          # "Old skin tone: ..." / "New skin tone: ..." in an "Appearance changed" record

FOLDER = "Skin Tones"
MAGIC = b"VF1SKIN\x00"
TAG = b"VF1V101\x00"
HEADER = 52
ENTRY = 64
MAX_ENTRIES = 400


def tone_name(tone: int) -> str:
    """A tone as the menus and the log write it: "Copper", or "Default" (15, or 0 for none yet)."""
    return TONE_NAMES[tone - 1] if 1 <= tone <= TONE_COUNT else DEFAULT_NAME


def inherit(father: int, mother: int, r100: int, r3: int, rn: int) -> int:
    """A baby's tone (vf1skin.cpp Inherit, the Virtual Villagers patcher's rule): `father`, `mother` 1..10, anything
    else for not known; r100, r3 and rn the rolls rand(100), rand(3) and rand(10). Always 1..10."""
    father = father if 1 <= father <= TONE_COUNT else 0
    mother = mother if 1 <= mother <= TONE_COUNT else 0
    if r100 < 5 or (father == 0 and mother == 0):
        return rn % TONE_COUNT + 1
    father, mother = father or mother, mother or father
    return min(max((father + mother) // 2 + r3 % 3 - 1, 1), TONE_COUNT)


@dataclass
class Person:
    slot: int
    sex: int
    name: bytes
    tone: int
    birth: int
    head: int
    body: int
    places: tuple[tuple[int, int], ...]
    person: int


@dataclass
class TonesFile:
    save_hash: int
    save_size: int
    generations: int
    parent_slot: int
    parent_sex: int
    people: list[Person]


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def read(data: bytes) -> TonesFile | None:
    """The file as vf1skin.dll reads it (vf1skin.cpp ReadSidecar), or None when the DLL would set it aside."""
    if len(data) < HEADER + 8 or data[:8] != MAGIC or data[12:20] != TAG:
        return None
    version, size = struct.unpack_from("<I", data, 8)[0], struct.unpack_from("<I", data, 20)[0]
    count = struct.unpack_from("<I", data, 48)[0]
    if version != 1 or size != len(data) or count > MAX_ENTRIES or len(data) != HEADER + count * ENTRY + 8:
        return None
    if struct.unpack_from("<Q", data, len(data) - 8)[0] != fnv1a64(data[:-8]):
        return None
    people = []
    for i in range(count):
        e = data[HEADER + i * ENTRY:HEADER + (i + 1) * ENTRY]
        slot, sex = struct.unpack_from("<ii", e, 0)
        name = e[8:34]
        tone, birth = e[34], e[35]
        head, body, g0, g1, p0, p1, person = struct.unpack_from("<iiiiiiI", e, 36)
        if not (-1 <= slot < 30) or sex not in (0, 1) or name[25] != 0:
            return None
        if not (tone <= TONE_COUNT or tone == TONE_DEFAULT) or birth > TONE_COUNT:
            return None
        places = tuple((g, p) for g, p in ((g0, p0), (g1, p1)) if g)
        people.append(Person(slot, sex, name.split(b"\0", 1)[0], tone, birth, head, body, places, person))
    save_hash, save_size, gens, pslot, psex = struct.unpack_from("<QIiii", data, 24)
    return TonesFile(save_hash, save_size, gens, pslot, psex, people)
