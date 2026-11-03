"""The text the patches add to Virtual Families 1, for translations: every string literal in the patcher's DLLs
(native/), sorted into the lines a player sees, each marked for translation, and the rest.

A line a player sees is marked in the C/C++ source with one of vf1fun's translation macros
(native/vf1fun/translate.inc):

    TR(L"...")           translated where it is used (a Windows dialog, message box or list)
    TR_N(L"...")         only marked: translated where it is shown (Template::Begin / Item, Message, Confirm and
                         the static tables that go through Tr()) -- for static tables and initialisers
    TR_A(room, "...")    a narrow line the game itself draws, translated now, at most `room` bytes
    TR_NA(room, "...")   the same, only marked (a static table)

`python tools/vf1_patch_text.py` writes data/vf1_patch_strings.json (shipped beside the patcher), which
patcher/vf1_translation_strings.py adds to the "Make a translation" template under the key source "patch", and
native/vf1tr/vf1tr_patch_formats.h. A line is a printf FORMAT ("format": true) when its TR(...) is the format
argument of a printf call (swprintf(buffer, size, TR(L"..."), ...)): only its own conversions are placeholders, and
vf1tr.dll hands vf1fun.dll a plain '%' of its translation as "%%" (translation_format.runtime_text).
tests/test_patch_text_coverage.py fails when a literal a player can see is not marked, when the JSON is out of
date, or when a DLL that shows no text starts calling a function that shows some.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
import translation_format as tfmt  # noqa: E402

NATIVE = ROOT / "native"
OUTPUT = ROOT / "data" / "vf1_patch_strings.json"
FORMATS_H = ROOT / "native" / "vf1tr" / "vf1tr_patch_formats.h"
# printf-like calls and the position of their format argument
FORMAT_ARGUMENT = {"swprintf": 2, "_snwprintf": 2, "snprintf": 2, "_snprintf": 2, "swprintf_s": 2,
                   "sprintf": 1, "wsprintfW": 1, "wsprintfA": 1}

# The DLLs, and whether each one shows text to the player (Windows dialogs or the game's own drawing).
DLLS = {
    "vf1fun": True,      # the Upgrades menu and its pages, messages, the behaviour captions, ...
    "vf1kids": False,    # Up to 28 Children: a sidecar file and its own log only
    "vf1logs": False,    # Family History: the log file (kept in English: the Family Tree Maker reads it)
    "vf1text": False,    # the in-game Unicode fonts: draws the game's text, adds none
    "vf1tr": False,      # Translations itself: its log only
}
# Calls that would put text on the screen: a DLL marked False above must call none of them.
SHOWS_TEXT = re.compile(r"\b(MessageBox[AW]?|DialogBox\w*|CreateDialog\w*|SetWindowText[AW]?|SetDlgItemText[AW]?|"
                        r"DrawText\w*|TextOut[AW]?|ExtTextOut[AW]?|ButtonSetText|LB_ADDSTRING|CB_ADDSTRING|"
                        r"LVM_INSERTITEM\w*|TTM_ADDTOOL\w*)\b")

# Those calls where they draw no text of the DLL's own.
SHOWS_NOTHING_OF_ITS_OWN = {
    "vf1text": {"glyph_gdi.inc: TextOutW"},       # draws one letter of the game's own text into a glyph bitmap
}

MARKERS = re.compile(r"\b(TR|TR_N)\(\s*$|\b(TR_A|TR_NA)\(\s*(\d+)\s*,\s*$")

# Literals in vf1fun that a player never sees, by the call they are an argument of. A literal anywhere else must be
# marked, or listed in NOT_SHOWN with its reason.
UNSEEN_CALLS = (
    "GetProcAddress", "GetModuleHandleW", "GetModuleHandleA", "LoadLibraryW", "LoadLibraryA", "LoadLibraryExW",
    "GetPrivateProfileStringW", "GetPrivateProfileIntW", "WritePrivateProfileStringW", "SettingOn", "ReadSetting",
    "WriteSetting", "ReadCount", "WriteCount", "Log", "LogLine", "OutputDebugStringA", "OutputDebugStringW",
    "wcscpy_s", "lstrcmpiW", "memcmp", "memcpy", "strcmp", "_wcsicmp", "wcscmp", "fopen", "_wfopen", "_wfopen_s",
    "CreateFileW", "snprintf", "_snwprintf", "PathAppendW", "wcscat_s", "Str", "SHGetFolderPathW",
    "SHGetKnownFolderPath", "RegOpenKeyExW", "RegQueryValueExW", "GetEnvironmentVariableW", "CreateMutexW",
    "FindWindowW", "RegisterClassW", "CreateFontW", "lstrcpyW",
    "sprintf_s",            # songs.inc: a file path and the songs' own debug log only
    "GiveLike",             # a like by its English name in the game's list (villager_upgrades.inc)
    "CreateWindowExW",      # a window class name
)

# Exact texts that are not shown although they are not in a call above; the reason is in the comment.
NOT_SHOWN = {
    "Segoe UI", "Segoe UI Historic",                      # font names
    "SDL2.dll", "SDL_GetKeyboardFocus", "SDL_GL_GetCurrentWindow", "SDL_GetWindowFlags", "SDL_SetWindowFullscreen",
    "vf1tr.dll", "vf1kids.dll", "vf1logs.dll", "vf1text.dll", "vf1font.dll", "vf1fun.dll", "kernel32.dll",
    "user32.dll", "gdiplus.dll", "shell32.dll",
    "VF1Tr_TextW", "VF1Tr_TextA", "VF1Tr_English",       # vf1tr.dll's functions (translate.inc)
    # file and folder names
    "\\Images\\male_heads00.png", "\\Images\\female_heads00.png", "%s\\LDW\\%s\\Virtual Families 1 Patcher Data",
    "\\Slot %d.ini", "Virtual Families 1 Patcher Data\\Outfits", "%s\\VF2 Songs\\%hs",
    "menu.ogg", "song1.ogg", "song2.ogg", "song3.ogg", "song4.ogg",
}
# The same, in one file only (the same word may be shown elsewhere).
NOT_SHOWN_IN = {
    # the keys of a slot's settings file
    "features.inc": {"BrokerageAccount", "FoodClub", "HealthPlan", "LuckyRock", "Maid", "Gardener", "PriceMultiplier",
                     "FoodClubLastDelivery", "SameSexMarriage", "RerollMarriageCandidates", "NextPregnancy",
                     "PatcherAchievements", "BankInterestPercent", "MaidNextVisit", "GardenerNextVisit"},
}


@dataclass
class Literal:
    dll: str
    path: str               # relative to the repository, with forward slashes
    line: int
    text: str               # the string as the program holds it
    wide: bool
    marker: str = ""        # "TR", "TR_N", "TR_A", "TR_NA" or ""
    room: int = 0           # TA / NA: the most it may hold, in bytes
    call: str = ""          # the function the literal is an argument of, if any
    argument: int = -1      # its position among that call's arguments (0 = the first)
    raw_context: str = field(default="", repr=False)

    @property
    def is_format(self) -> bool:
        """The format argument of a printf call (marked TR: translated where it is used)."""
        return self.marker == "TR" and FORMAT_ARGUMENT.get(self.call, -2) == self.argument


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": "\0", "a": "\a", "?": "?"}


def _unescape(body: str) -> str:
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "x":
            j = i + 2
            while j < len(body) and body[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(chr(int(body[i + 2:j], 16)))
            i = j
        elif nxt == "u":
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        elif nxt in "01234567" and nxt != "0" or (nxt == "0" and i + 2 < len(body) and body[i + 2] in "01234567"):
            j = i + 1
            while j < len(body) and j < i + 4 and body[j] in "01234567":
                j += 1
            out.append(chr(int(body[i + 1:j], 8)))
            i = j
        else:
            out.append(_ESCAPES[nxt])
            i += 2
    return "".join(out)


def _tokens(source: str):
    """(kind, start, end, text) for string literals, with comments blanked: kind 'str' or 'wstr'. Adjacent literals
    (only whitespace between them) are joined as C joins them."""
    i, n = 0, len(source)
    code = list(source)
    found = []
    while i < n:
        c = source[i]
        if source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                code[k] = " "
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if code[k] != "\n":
                    code[k] = " "
            i = j
        elif c == "'":
            j = i + 1
            while source[j] != "'":
                j += 2 if source[j] == "\\" else 1
            i = j + 1
        elif c == '"':
            wide = i > 0 and source[i - 1] == "L" and (i < 2 or not (source[i - 2].isalnum() or source[i - 2] == "_"))
            if i > 0 and source[i - 1] == "R" or (i > 1 and source[i - 2:i] == "LR"):
                raise ValueError("raw string literals are not supported")
            j = i + 1
            while source[j] != '"':
                if source[j] == "\n":
                    raise ValueError(f"unterminated string at {i}")
                j += 2 if source[j] == "\\" else 1
            found.append(["wstr" if wide else "str", i - (1 if wide else 0), j + 1, _unescape(source[i + 1:j])])
            i = j + 1
        else:
            i += 1
    code_text = "".join(code)
    joined = []
    for tok in found:
        if joined and code_text[joined[-1][2]:tok[1]].strip() == "" and "#" not in code_text[joined[-1][2]:tok[1]]:
            joined[-1][2] = tok[2]
            joined[-1][3] += tok[3]
            continue
        joined.append(tok)
    return code_text, joined


def _enclosing_call(code: str, start: int) -> str:
    """The name of the call whose argument list holds position `start`, if any (same statement)."""
    return _call_and_argument(code, start)[0]


def _call_and_argument(code: str, start: int) -> tuple[str, int]:
    """(the call whose argument list holds position `start`, the argument's position in it), ("", -1) if none."""
    depth = 0
    commas = 0
    i = start - 1
    while i >= 0:
        c = code[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", code[max(0, i - 80):i])
                if m and m.group(1) in ("TR", "TR_N", "TR_A", "TR_NA"):   # the marker: the call around it
                    commas = 0
                    i -= 1
                    continue
                return (m.group(1), commas) if m else ("", -1)
            depth -= 1
        elif c == "," and depth == 0:
            commas += 1
        elif c in ";{}" and depth == 0:
            return "", -1
        i -= 1
    return "", -1


def literals(dll: str) -> list[Literal]:
    out: list[Literal] = []
    for path in sorted((NATIVE / dll).glob("*")):
        if path.suffix not in (".c", ".cpp", ".h", ".inc"):
            continue
        source = path.read_text(encoding="utf-8")
        code, toks = _tokens(source)
        for kind, start, end, text in toks:
            before = code[max(0, start - 40):start]
            line_start = code.rfind("\n", 0, start) + 1
            if code[line_start:start].lstrip().startswith("#"):
                continue                                       # #include, #pragma, #error
            m = MARKERS.search(before)
            marker, room = "", 0
            if m:
                marker = m.group(1) or m.group(2)
                room = int(m.group(3) or 0)
            call, argument = _call_and_argument(code, start)
            out.append(Literal(dll, path.relative_to(ROOT).as_posix(), source.count("\n", 0, start) + 1, text,
                               kind == "wstr", marker, room, call, argument, code[line_start:end]))
    return out


def looks_shown(text: str) -> bool:
    """A literal that could be words for a player: two letters in a row, and not a format of only placeholders."""
    if not re.search(r"[A-Za-z]{2}", text):
        return False
    words = re.sub(r"%[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|I64|I32|w)?[diouxXeEfgGcsSp%]", "", text)
    return bool(re.search(r"[A-Za-z]{2}", words))


def shows_text(dll: str) -> list[str]:
    """Calls that put text on the screen in a DLL's sources (code only, comments left out)."""
    hits = []
    for path in sorted((NATIVE / dll).glob("*")):
        if path.suffix in (".c", ".cpp", ".h", ".inc"):
            code, _ = _tokens(path.read_text(encoding="utf-8"))
            hits += [f"{path.name}: {m.group(1)}" for m in SHOWS_TEXT.finditer(code)]
    return [h for h in hits if h not in SHOWS_NOTHING_OF_ITS_OWN.get(dll, ())]


def unmarked(dll: str = "vf1fun") -> list[Literal]:
    """Literals a player may see that are not marked for translation."""
    return [lit for lit in literals(dll) if not lit.marker and looks_shown(lit.text)
            and lit.call not in UNSEEN_CALLS and lit.text not in NOT_SHOWN
            and lit.text not in NOT_SHOWN_IN.get(lit.path.rsplit("/", 1)[-1], ())]


# --------------------------------------------------------------------------- the strings for the template

MAX_LINE = 1000
WIDE_MAX = 600


def wide_room(english: str) -> int:
    """The most a translation of a wide (Windows) line may hold, in UTF-8 bytes; vf1tr.c's patch_room_w is the same
    rule: three times its English, at least 80, at most 600. The dialog templates hold that much
    (tests/test_patch_text_coverage.py adds it up), and every swprintf in vf1fun.dll is told its buffer's size
    (the same test checks the calls), so a long line filled into a fixed buffer is cut there, never written past."""
    n = len(english.encode("utf-8"))
    return min(WIDE_MAX, max(80, 3 * n))


def key_id(lit: Literal) -> str:
    """The stable part of a key: the DLL and the English's own words (a-z, 0-9, '_'), at most 60 characters."""
    words = re.sub(r"[^a-z0-9]+", "_", lit.text.lower()).strip("_")[:60].strip("_") or "text"
    return f"{lit.dll}.{words}"


def strings() -> list[dict]:
    """Every marked line, once each (the same English twice is one line), in source order."""
    seen: dict[str, dict] = {}
    for dll, shown in DLLS.items():
        if not shown:
            continue
        for lit in literals(dll):
            if not lit.marker:
                continue
            room = lit.room if lit.marker in ("TR_A", "TR_NA") else wide_room(lit.text)
            if lit.text in seen:
                seen[lit.text]["room"] = min(seen[lit.text]["room"], room)
                seen[lit.text]["where"].append(f"{lit.path}:{lit.line}")
                seen[lit.text]["format"] = seen[lit.text]["format"] or lit.is_format
                continue
            seen[lit.text] = {"id": key_id(lit), "english": lit.text, "room": min(room, MAX_LINE),
                              "drawn_by_game": lit.marker in ("TR_A", "TR_NA"), "format": lit.is_format,
                              "where": [f"{lit.path}:{lit.line}"]}
    ids: dict[str, int] = {}
    for row in seen.values():                       # two different lines with the same first words
        n = ids.get(row["id"], 0)
        ids[row["id"]] = n + 1
        if n:
            row["id"] = f"{row['id']}.{n + 1}"
    return list(seen.values())


def render() -> str:
    data = {"comment": "Written by tools/vf1_patch_text.py from native/; do not edit.", "strings": strings()}
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def render_formats_h() -> str:
    """native/vf1tr/vf1tr_patch_formats.h: the patch lines vf1fun.dll uses as a printf format, by the hash in their
    key (the first 8 hex digits of the SHA-256 of the English): vf1tr.dll writes a plain '%' of their translation
    as "%%"."""
    hashes = sorted({tfmt.key_hash(row["english"]) for row in strings() if row["format"]})
    body = "\n".join(f"    0x{h}u," for h in hashes)
    return "\n".join([
        "/* Written by tools/vf1_patch_text.py from native/; do not edit. */",
        "#pragma once",
        "/* The patches' lines vf1fun.dll hands swprintf as its FORMAT, by the hash in their key: a plain '%' of their",
        "   translation is written as \"%%\" (translation_format.runtime_text). */",
        f"#define VF1TR_PATCH_FORMAT_COUNT {len(hashes)}",
        "static const unsigned int VF1TR_PATCH_FORMAT[] = {\n" + body + "\n    0u\n};",
        "",
    ])


def main() -> int:
    problems = unmarked()
    for dll, shown in DLLS.items():
        if not shown:
            problems += shows_text(dll)
    if problems:
        for p in problems:
            print("not marked for translation:", p, file=sys.stderr)
        return 1
    OUTPUT.write_text(render(), encoding="utf-8", newline="\n")
    FORMATS_H.write_text(render_formats_h(), encoding="utf-8", newline="\n")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(strings())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
