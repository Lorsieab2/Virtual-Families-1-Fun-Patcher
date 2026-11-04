"""The one rule for the text inside Virtual Families 1's saves and logs (Render Unicode with In-Game Fonts).

Virtual Families 1 keeps every name as a NUL-terminated byte string in a fixed field of the save (the family
name at theGameState+0x1B12C, the slot menu's names, each person's name and parents' names; see
docs/vf1-save-format.md). The stock game only ever writes printable ASCII there: its text box drops any typed
character that is not one byte (SDL_TEXTINPUT at 0x4049BB) and any byte from 0x80 (0x40DB0F).

With the patch on, a name may hold any Unicode text, stored like this (the shared Unicode spec's per-character
write rule and per-sequence read rule, the Virtual Villagers Fun Patcher's):

* ASCII stays exactly as it is, byte for byte;
* WRITING, per character: a character Windows-1252 has is its one byte, any other character is UTF-8, in the same
  string ("Zo\u00eb \u65e5\u672c" keeps a stock-readable \u00eb beside the Japanese). If the mixed bytes would read back
  as different text (a Windows-1252 "\u00c3" followed by "\u00a9" spells the UTF-8 sequence of "\u00e9"), every non-ASCII
  character of that string is written as UTF-8 instead. Nothing is added to the game's records;
* READING, per sequence: each well-formed UTF-8 sequence (shortest form, no surrogate, nothing past U+10FFFF) is its
  character, and every other byte is read the old single-byte way, one character (Windows-1252, with the five
  bytes Windows-1252 leaves unassigned read as Latin-1). So an old or hand-edited save reads exactly as before, a
  pure UTF-8 name (every name this patcher wrote before the rule) reads as it always did, and a mixed string reads
  right;
* a name is cut at a byte limit only between whole characters (grapheme clusters: a letter with its
  accents, an emoji with its skin tone, joiners and variation selectors, a flag's two letters), never inside
  one.

Every reader in the patcher (the logs, the Family Tree, Rename Family, Copy Player Slot, the Game Text tool)
uses `decode` and `encode_field`; vf1text.dll (native/vf1text) decodes with the same rule and the same
cluster table, which `cluster_table_c` writes from here (scripts/build_vf1_text_tables.py).

The unpatched game shows a UTF-8 name as one Latin-1 letter per byte ("Zoë" as "ZoÃ«"; bytes 0x80..0xA1,
which its fonts lack, as the first glyph, "!"). It never crashes on them (tests/test_vf1_text_emulation.py
runs its text drawing on such names).
"""
from __future__ import annotations

import unicodedata

__all__ = [
    "decode", "is_utf8", "encode", "encode_field", "clusters", "char_count", "cut_to_bytes",
    "is_cluster_extender", "EXTENDER_RANGES", "NAME_BOX_BYTES", "NAME_MARK",
]

# --------------------------------------------------------------------------- the one name limit
# THE limit of every name box (the game's own boxes, vf1fun.dll's windows and the patcher's tools), shared with the
# owner's other patchers (Virtual Villagers, Virtual Families 2, Fish / Plant Tycoon): up to 1,200 bytes as stored,
# with NO separate character cap (owner decision, 2026-11-03: "All games: up to 1,200"). That is up to 1,200 plain
# ASCII letters, and fewer when letters need more bytes. Change it here only: scripts/build_vf1_text_tables.py writes
# it into native/vf1text/extenders.inc for the DLLs, and tests/test_name_limit.py fails if another file spells it.
#
# Why 1,200: the LDW engine's text box setup ldwTextControlImpl::SetEditable 0x40D370 caps every box's buffer at 0x4B0
# = 1,200 bytes (0x40D3B3), the same cap Fish / Plant Tycoon's engine has. The cap is not patched past: every patcher
# keeps it. One code point is at most 4 bytes of UTF-8, so buffers sized for characters are sized 4 x the characters
# (the worst-case box maths), and a box stops taking text at 1,200 bytes, cutting only at whole characters.
NAME_BOX_BYTES = 1200                      # the box buffer (plus its NUL), the engine's own cap
# A name longer than its save field is stored there as a short form ending with this mark (unique in the save, so it
# names one family member); the whole name is in the save's Names file (patcher/vf1_names.py).
NAME_MARK = "..."

# Windows-1252's assignments for 0x80..0x9F; the five unassigned bytes stay Latin-1 (C1 controls).
_CP1252_HIGH = {
    0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E, 0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021,
    0x88: 0x02C6, 0x89: 0x2030, 0x8A: 0x0160, 0x8B: 0x2039, 0x8C: 0x0152, 0x8E: 0x017D, 0x91: 0x2018,
    0x92: 0x2019, 0x93: 0x201C, 0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014, 0x98: 0x02DC,
    0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153, 0x9E: 0x017E, 0x9F: 0x0178,
}


def single_byte_char(byte: int) -> str:
    """The old single-byte reading of one byte."""
    return chr(_CP1252_HIGH.get(byte, byte))


def is_utf8(data: bytes) -> bool:
    """True when ``data`` is well-formed UTF-8 (no overlong forms, no surrogates, nothing past U+10FFFF)."""
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return True


def _sequence_length(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 2
    if 0xE0 <= lead <= 0xEF:
        return 3
    if 0xF0 <= lead <= 0xF4:
        return 4
    return 0


def decode_bytes(data: bytes) -> str:
    """``data`` (no NUL handling) by the per-sequence read rule: each well-formed UTF-8 sequence is its character,
    every other byte is its Windows-1252 character."""
    if data.isascii():
        return data.decode("ascii")
    out: list[str] = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b < 0x80:
            out.append(chr(b))
            i += 1
            continue
        k = _sequence_length(b)
        if k and i + k <= n:
            try:
                out.append(data[i:i + k].decode("utf-8"))
                i += k
                continue
            except UnicodeDecodeError:
                pass
        out.append(single_byte_char(b))
        i += 1
    return "".join(out)


def decode(data: bytes) -> str:
    """The text of a game string (the bytes up to its first NUL, if any), by the one rule above."""
    end = data.find(b"\0")
    if end >= 0:
        data = data[:end]
    return decode_bytes(data)


def decode_lines(data: bytes) -> str:
    """A text file the patcher's logs write (names copied from the save as they are): each line by the rule
    above, so a log with names from both before and after the patch reads right."""
    return "\n".join(decode(line) if b"\0" not in line else line.decode("latin-1")
                     for line in data.split(b"\n"))


_CP1252_BYTE = {cp: byte for byte, cp in _CP1252_HIGH.items()}
_LATIN1_CONTROLS = (0x81, 0x8D, 0x8F, 0x90, 0x9D)      # the five bytes Windows-1252 leaves unassigned


def single_byte_of(ch: str) -> int | None:
    """The one byte that reads back as ``ch`` (Windows-1252, the five unassigned bytes as the Latin-1 control with
    the same number), or None when ``ch`` has no byte."""
    cp = ord(ch)
    if cp < 0x80 or 0xA0 <= cp <= 0xFF:
        return cp
    if cp in _CP1252_BYTE:
        return _CP1252_BYTE[cp]
    if cp in _LATIN1_CONTROLS:
        return cp
    return None


def encode(text: str) -> bytes:
    """``text`` as the patch stores it, by the per-character write rule: a Windows-1252 character is its one byte,
    any other character UTF-8, in the same string; every non-ASCII character is UTF-8 when the mixed bytes would
    read back as different text. ASCII is unchanged. NUL cannot be stored."""
    if "\0" in text:
        raise ValueError("a game string cannot hold NUL")
    if text.isascii():
        return text.encode("ascii")
    out = bytearray()
    for ch in text:
        b = single_byte_of(ch)
        out += bytes((b,)) if b is not None else ch.encode("utf-8")
    mixed = bytes(out)
    if decode_bytes(mixed) == text:
        return mixed
    return text.encode("utf-8")


# --------------------------------------------------------------------------- grapheme clusters
# A simplified extended grapheme cluster, the same one vf1text.dll uses: a cluster is one character plus
# every following extender (combining marks Mn/Mc/Me, variation selectors, emoji skin tones, tag characters,
# ZERO WIDTH JOINER and the character after it unless that is CR or LF), two regional indicators make one flag, and
# CR LF is one character.
_ZWJ = 0x200D
_EXTRA_EXTENDERS = (
    (0x200C, 0x200C),          # ZERO WIDTH NON-JOINER
    (0x200D, 0x200D),          # ZERO WIDTH JOINER (also joins the next character)
    (0xFE00, 0xFE0F),          # variation selectors
    (0x1F3FB, 0x1F3FF),        # emoji skin tones
    (0xE0020, 0xE007F),        # tag characters (subdivision flags)
    (0xE0100, 0xE01EF),        # variation selectors supplement
)


def build_extenders() -> tuple[tuple[int, int], ...]:
    """The extender ranges: Unicode 18.0's marks (general category Mn, Mc and Me, vf1_unicode18, from the Unicode
    Character Database; Python's own unicodedata is older) and the extra extenders above, merged. The table is
    fixed so the patcher and vf1text.dll never disagree (scripts/build_vf1_text_tables.py writes extenders.inc)."""
    import vf1_unicode18
    spans = sorted(list(vf1_unicode18.EXTENDER_MARKS) + list(_EXTRA_EXTENDERS))
    ranges: list[list[int]] = []
    for a, b in spans:
        if ranges and a <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], b)
        else:
            ranges.append([a, b])
    return tuple((a, b) for a, b in ranges)


# Unicode 18.0 (vf1_unicode18), from build_extenders().
EXTENDER_RANGES: tuple[tuple[int, int], ...] = build_extenders()
_EXTENDER_SET = frozenset(cp for a, b in EXTENDER_RANGES for cp in range(a, b + 1))


def is_cluster_extender(cp: int) -> bool:
    return cp in _EXTENDER_SET


def _regional(cp: int) -> bool:
    return 0x1F1E6 <= cp <= 0x1F1FF


def clusters(text: str, *, draw: bool = False) -> list[str]:
    """``text`` split into whole characters as a player sees them (the shared Unicode spec's cluster rule, the same
    as the Virtual Families 2 patcher's): CR LF is one character, and a ZERO WIDTH JOINER joins the next character
    unless that is CR or LF.

    ``draw=True`` gives the pieces the game's draw and measure loops take one at a time: the same, except that CR LF
    is CR and then LF, so a line break inside text is drawn exactly as before (the draw goes to the next line on a
    lone "\\n", vf1text.dll's ``DrawEnd``)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        if text[i] == "\r" and j < n and text[j] == "\n":
            if draw:
                out.append("\r")
                i = j
                continue
            j += 1
        elif _regional(ord(text[i])) and j < n and _regional(ord(text[j])):
            j += 1
        while j < n:
            cp = ord(text[j])
            if cp == _ZWJ:
                j += 1
                if j < n and text[j] not in "\r\n":
                    j += 1          # the joined character belongs to the cluster
                continue
            if cp in _EXTENDER_SET:
                j += 1
                continue
            break
        out.append(text[i:j])
        i = j
    return out


def char_count(text: str) -> int:
    """How many characters a player sees (grapheme clusters)."""
    return len(clusters(text))


def cut_to_bytes(text: str, max_bytes: int) -> str:
    """The longest start of ``text`` whose stored bytes (``encode``) fit in ``max_bytes``, cut between whole
    characters. (The stored length of a start never shrinks as the start grows, so a search finds it.)"""
    parts = clusters(text)
    if text.isascii() and "\r\n" not in text:
        return text[:max(0, max_bytes)]
    lo, hi = 0, len(parts)                       # the largest count whose bytes fit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(encode("".join(parts[:mid]))) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return "".join(parts[:lo])


def encode_field(text: str, field_size: int) -> bytes:
    """``text`` for a fixed field of ``field_size`` bytes: stored by the per-character rule, cut between whole
    characters so that it and its NUL fit, padded with NULs to the field size."""
    if field_size < 1:
        raise ValueError("a field holds at least its NUL")
    data = encode(cut_to_bytes(text, field_size - 1))
    return data + b"\0" * (field_size - len(data))


def cluster_table_c() -> str:
    """The extender ranges as a C table, for native/vf1text (generated, never edited by hand)."""
    lines = [
        "// Generated by scripts/build_vf1_text_tables.py from patcher/vf1_text.py (EXTENDER_RANGES).",
        "// Do not edit: the patcher's readers and vf1text.dll must split characters the same way.",
        "#ifndef VF1_NAME_BOX_BYTES",
        f"#define VF1_NAME_BOX_BYTES {NAME_BOX_BYTES}    // vf1_text.NAME_BOX_BYTES: every name box's limit, in bytes",
        f'#define VF1_NAME_MARK "{NAME_MARK}"           // vf1_text.NAME_MARK: the end of a short form',
        "#endif",
        f"static const unsigned ExtenderRanges[{len(EXTENDER_RANGES)}][2] = {{",
    ]
    row: list[str] = []
    for a, b in EXTENDER_RANGES:
        row.append(f"{{0x{a:X},0x{b:X}}}")
        if len(row) == 6:
            lines.append("    " + ",".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ",".join(row) + ",")
    lines.append("};")
    return "\n".join(lines) + "\n"
