"""Every piece of text a patch adds to Virtual Families 1 can be translated (the owner, 2026-11-02: "what if we wanted
to translate patch-exclusive content?").

tools/vf1_patch_text.py reads native/: every string literal in every patcher DLL is either marked for translation
(native/vf1fun/translate.inc: TR, TR_N, TR_A, TR_NA) or is text a player never sees (a file name, a settings key, a
log line); a DLL that shows no text calls nothing that shows text. The marked lines are in
data/vf1_patch_strings.json, from which the "Make a translation" template takes them (key "patch/<dll>.<words>~<hash>",
after the game's own lines); vf1tr.dll finds a translation by its English (tests/test_translations_runtime.py runs
it). The executable's own patch (the loader stub) adds no text. Each line has a room no buffer can be overrun by:
the dialog templates hold every text at its room, every swprintf is given its buffer's size, and a caption the game
draws is cut to its label."""
from __future__ import annotations

import json
import re

import pytest

from conftest import ROOT

import translation_format as tfmt
import vf1_patch_text as pt
import vf1_translation_strings as vts

FUN = ROOT / "native" / "vf1fun"


def source(name: str) -> str:
    return (FUN / name).read_text(encoding="utf-8")


def code(path) -> str:
    """The source with comments blanked (the scanner's own reading)."""
    return pt._tokens(path.read_text(encoding="utf-8"))[0]


# ---------------------------------------------------------------------------------------------- coverage


def test_every_dll_is_listed():
    folders = {p.name for p in (ROOT / "native").iterdir() if p.is_dir()}
    assert folders == set(pt.DLLS), "a new DLL: list it in tools/vf1_patch_text.DLLS (does it show text?)"


def test_every_literal_a_player_can_see_is_marked():
    missing = [f"{lit.path}:{lit.line} {lit.text!r}" for dll, shown in pt.DLLS.items() if shown
               for lit in pt.unmarked(dll)]
    assert missing == [], "not marked for translation (native/vf1fun/translate.inc):\n" + "\n".join(missing)


@pytest.mark.parametrize("dll", [d for d, shown in pt.DLLS.items() if not shown])
def test_a_dll_that_shows_no_text_calls_nothing_that_shows_text(dll):
    assert pt.shows_text(dll) == []


def test_the_scanner_finds_a_new_unmarked_line(tmp_path, monkeypatch):
    folder = tmp_path / "native" / "vf1fun"
    folder.mkdir(parents=True)
    (folder / "x.inc").write_text('static void F(HWND d) {\n    Message(d, L"A new message.");\n'
                                  '    Message(d, TR_N(L"A marked one."));\n'
                                  '    GetPrivateProfileIntW(L"Patches", L"Key", 0, path);\n'
                                  '    swprintf(s, 64, TR(L"%d of %d"), a, b);\n}\n', encoding="utf-8")
    monkeypatch.setattr(pt, "NATIVE", tmp_path / "native")
    monkeypatch.setattr(pt, "ROOT", tmp_path)
    assert [lit.text for lit in pt.unmarked("vf1fun")] == ["A new message."]
    assert [(lit.text, lit.marker) for lit in pt.literals("vf1fun") if lit.marker] == [
        ("A marked one.", "TR_N"), ("%d of %d", "TR")]


def test_every_visible_kind_of_text_is_marked():
    """Spot checks across the pages: the menu, a page title, a message, a format, a static table, a caption."""
    english = {row["english"] for row in pt.strings()}
    for text in ("Upgrades", "Upgrades Menu", "Cheat Upgrades", "No Money", "Set your money to $0?",
                 "Money now: $%.0f        Interest rate now: %.1f%%", "Brokerage Account", "Centenarian",
                 "Have a person reach age 70.", "Time Warp", "Watching a movie", "Virtual Families 1 Fun Patcher",
                 "This family already has six children.", "Female", "Male"):
        assert text in english, text


def test_the_json_is_up_to_date():
    assert pt.OUTPUT.read_text(encoding="utf-8") == pt.render(), "run python tools/vf1_patch_text.py"


# ---------------------------------------------------------------------------------------------- the template


def test_every_patch_line_has_a_key_in_the_template(monkeypatch):
    rows = pt.strings()
    assert len(rows) > 400
    monkeypatch.setattr(vts, "read_table", lambda exe: {4: ("eString_Continue", "Continue")})
    entries = vts.entries_for(b"")
    keys = {e.key for e in entries}
    assert entries[0].key.startswith("strings/4~")                      # the game's lines first
    for row in rows:
        assert tfmt.make_key("patch", row["id"], row["english"]) in keys, row["english"]
    patch = [e for e in entries if e.key.startswith("patch/")]
    assert len(patch) == len(rows) == len({e.key for e in patch}) == len({vts.tfmt.base_key(e.key) for e in patch})
    for e in patch:
        assert e.max_length and e.notes.startswith("vf1fun: ")
    new = tfmt.new_file("vf1", entries, "Français", "fr")
    assert {r.key for r in new.rows} == keys


def test_rooms():
    for row in pt.strings():
        n = len(row["english"].encode("utf-8"))
        if row["drawn_by_game"]:
            assert n <= row["room"] <= 60, row
        else:
            assert row["room"] == min(600, max(80, 3 * n)), row


def test_the_shipped_json_is_read_beside_the_patcher():
    package = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert '"vf1_patch_strings.json"' in package
    assert vts.PATCH_JSON.name == "vf1_patch_strings.json" and vts.PATCH_JSON.is_file()


# ---------------------------------------------------------------------------------------------- the executable's patch


def test_the_executable_patch_adds_no_text():
    """The loader stub patcher/vf1_patcher.py writes into the executable names only DLLs and functions."""
    stub = bytes.fromhex(json.loads((ROOT / "patcher" / "stub.json").read_text(encoding="utf-8"))["code"])
    narrow = {m.decode() for m in re.findall(rb"[\x20-\x7e]{4,}", stub)}
    wide = {m.decode("utf-16-le") for m in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", stub)}
    assert narrow <= {"kernel32.dll", "GetModuleFileNameW", "LoadLibraryW", "VF1Fun_Startup", "VF1Fun_StoreCreated",
                      "VF1Fun_Tick"}, narrow
    assert all(w.endswith("Virtual Families 1 Patcher Files\\vf1fun.dll") for w in wide), wide


# ---------------------------------------------------------------------------------------------- room


def _calls(text: str, name: str):
    for m in re.finditer(r"\b%s\s*\(" % re.escape(name), text):
        depth, i, args, start = 0, m.end(), [], m.end()
        while True:
            c = text[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    args.append(text[start:i].strip())
                    break
                depth -= 1
            elif c == "," and depth == 0:
                args.append(text[start:i].strip())
                start = i + 1
            elif c == '"':
                i += 1
                while text[i] != '"':
                    i += 2 if text[i] == "\\" else 1
            i += 1
        yield args


def test_every_swprintf_is_told_its_buffer_size_and_nothing_copies_text_unbounded():
    for path in sorted(FUN.glob("*")):
        if path.suffix not in (".cpp", ".inc"):
            continue
        text = code(path)
        for args in _calls(text, "swprintf"):
            assert len(args) >= 3 and not args[1].startswith(("L\"", "TR")), (path.name, args)
        for bad in ("wcscpy(", "wcscat(", "lstrcpyW(", "lstrcatW(", "wsprintfW(", "_swprintf(", "strcpy(", "strcat(",
                    " sprintf("):
            assert bad not in text, (path.name, bad)


def test_the_dialog_templates_hold_every_text_at_its_room():
    """Template::buf (WORDs) holds each page with every title and control text as long as its room allows."""
    words = int(re.search(r"WORD buf\[(\d+)\]", source("vf1fun.cpp")).group(1))
    rooms = {row["english"]: row["room"] for row in pt.strings()}
    pages = 0
    for path in sorted(FUN.glob("*")):
        if path.suffix not in (".cpp", ".inc"):
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"static Template &(\w+)\(\) \{(.*?)\n\}", text, re.S):
            body = m.group(2)
            items = body.count("t.Item(") + 1
            literals = [pt._unescape(x) for x in re.findall(r'TR_N\(L"((?:[^"\\]|\\.)*)"\)', body)]
            need = 64 + items * (1 + 12 + 2 + 1 + 1) + sum(rooms[t] + 1 for t in literals)
            assert need <= words, (m.group(1), need, words)
            pages += 1
    assert pages >= 12


def test_tables_and_captions_are_translated_where_they_are_shown():
    pages, services, achievements, labels = (source(n) for n in ("pages.inc", "services.inc",
                                                                 "patcher_achievements.inc", "labels.inc"))
    assert not re.search(r"(?<!Tr\()\bp\.name\b", pages.split("static void FillPurchases")[1])
    assert not re.search(r"(?<!Tr\()kPurchases\[sel\]\.what", pages)
    assert not re.search(r"(?<!Tr\()kServices\[\w+\]\.(name|what)", services)
    assert "Tr(kAchievements[i].name), Tr(kAchievements[i].how)" in achievements
    assert "src = TrA(c.v[0], 39)" in labels and "src = TrA(c.v[r - 1], 39)" in labels
    for lit in pt.literals("vf1fun"):
        if lit.marker in ("TR_A", "TR_NA"):
            assert len(lit.text.encode("utf-8")) <= lit.room, lit
        if lit.marker == "TR_NA":
            assert lit.path.endswith("labels.inc") and lit.room == 39, lit
        if lit.marker == "TR_N":
            assert lit.call in ("Item", "Begin", "Message", "Confirm") or \
                lit.path.rsplit("/", 1)[-1] in ("pages.inc", "services.inc", "patcher_achievements.inc",
                                                "vf1fun.cpp"), lit
    cpp = source("vf1fun.cpp")
    assert "title = Tr(title);" in cpp and "text = Tr(text);" in cpp
    assert cpp.count("MessageBoxW(owner, Tr(text), TR(L\"Virtual Families 1 Fun Patcher\")") == 2


def test_the_runtime_has_what_vf1fun_and_vf1logs_ask_for():
    tr = (ROOT / "native" / "vf1tr" / "vf1tr.c").read_text(encoding="utf-8")
    for name in ("VF1Tr_TextW", "VF1Tr_TextA", "VF1Tr_English", "VF1Tr_EnglishOf"):
        assert f"__declspec(dllexport) const" in tr and f"__cdecl {name}(" in tr, name
    assert "#define PATCH_WIDE_MIN 80" in tr and "#define PATCH_WIDE_MAX 600" in tr and "english_n * 3" in tr
    assert pt.WIDE_MAX == 600
    inc = source("translate.inc")
    assert '"VF1Tr_TextW"' in inc and '"VF1Tr_TextA"' in inc and '"VF1Tr_English"' in inc


def test_the_family_history_log_stays_in_english():
    logs = (ROOT / "native" / "vf1logs" / "vf1logs.cpp").read_text(encoding="utf-8")
    word = logs[logs.index("static const char *Word(int id)"):]
    word = word[:word.index("\n}\n")]
    assert '"VF1Tr_English"' in word and word.index("english(id)") < word.index("LOGS_STRINGS_GET_STRING")
    assert "t.Name(EnglishOf(*(const char *const *)(d + LOGS_EVENT_DIALOG_TITLE))" in logs
    likes = source("villager_upgrades.inc")
    assert "GameEnglish(0x45B)" in likes and "GameEnglish(0x45C)" in likes
    limits = json.loads((ROOT / "data" / "vf1_translation_limits.json").read_text(encoding="utf-8"))
    assert list(limits["never"]) == ["2"]                                  # only the decimal point
