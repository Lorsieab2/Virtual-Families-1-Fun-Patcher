"""Translations in the game (native/vf1tr): the REAL compiled vf1tr.dll on the REAL vanilla executable, run in
Unicorn (tests/translations_emu.py), against the patcher's own reading of the same file (translation_format,
vf1_translation_strings).  Needs VF1_VANILLA_DIR and the MSVC toolchain; skips without them."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import translation_format as tfmt  # noqa: E402
import vf1_translation_strings as vts  # noqa: E402

VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")
INI = "C:\\Game\\Virtual Families 1 Patcher Files\\Translation.ini"


def build_env():
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    return dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")


@pytest.fixture(scope="module")
def dll(tmp_path_factory):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("tr_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_tr.bat")], capture_output=True, text=True,
                       env=dict(build_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr          # /W4 /WX
    return out / "vf1tr.dll"


@pytest.fixture(scope="module")
def exe(vanilla_dir):
    return vanilla_dir / "Virtual Families.exe"


@pytest.fixture(scope="module")
def table(exe):
    return vts.read_table(exe.read_bytes())


@pytest.fixture(scope="module")
def entries(exe):
    return {e.key: e for e in vts.entries_for(exe.read_bytes())}


def ini(path: str = "C:\\Translations\\Virtual Families - Test.txt") -> bytes:
    return ("\ufefflanguage=Test\r\nfile=" + path + "\r\n").encode("utf-8")


def world(exe, dll, rows: list[tuple[str, str, str]], unicode_dll=False, code="fr", extra: dict | None = None):
    import translations_emu as te
    tf = tfmt.new_file("vf1", [tfmt.Entry(k, en) for k, en, _t in rows], "Test", code)
    for row, (_k, _en, tr) in zip(tf.rows, rows):
        row.translation = tr
    files = {INI: ini(), te.CHOSEN: tfmt.to_bytes(tf)}
    files.update(extra or {})
    w = te.TranslationWorld(exe, dll, files, unicode_dll=unicode_dll)
    w.start()
    return w, tf


def key(sid: int, table) -> tuple[str, str]:
    english = table[sid][1]
    return tfmt.make_key("strings", str(sid), english), english


def first(table, test, skip=()):
    return next(sid for sid, (_k, en) in sorted(table.items()) if test(en) and sid not in skip)


# ---------------------------------------------------------------------------------------------- string replacement


def test_translated_lines_replace_the_games_own_and_the_rest_stays_english(exe, dll, table):
    done = table[0x41A][1]                       # "Done": the store's button
    k, en = key(0x41A, table)
    other = first(table, lambda t: t == "Continue")
    w, _tf = world(exe, dll, [(k, en, "Terminé")])
    assert w.installed == 1, w.log()
    assert w.get_string(0x41A) == "Terminé".encode("cp1252")          # through the game's own GetString
    assert w.get_string(other) == table[other][1].encode("cp1252")   # untranslated: English
    assert done == "Done"
    assert "1 lines used" in w.log()


def test_unicode_settings_get_utf8(exe, dll, table):
    k, en = key(0x41A, table)
    w, _tf = world(exe, dll, [(k, en, "Готово")], unicode_dll=True)
    assert w.get_string(0x41A) == "Готово".encode("utf-8")
    w2, _tf = world(exe, dll, [(k, en, "Готово")])
    assert w2.get_string(0x41A) == b"??????"                           # Windows-1252 without the Unicode DLLs


def test_the_games_own_template_fills_a_translated_person_choice(exe, dll, table):
    sid = first(table, lambda t: "{He/She}" in t and "{name}" in t)
    k, en = key(sid, table)
    translation = "{name} : {Il/Elle} va bien. {name: m=Il est prêt | f=Elle est prête}."
    w, tf = world(exe, dll, [(k, en, translation)])
    assert not tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1").errors
    assert w.get_string(sid) == "{name} : {Il/Elle} va bien. {Il est prêt/Elle est prête}.".encode("cp1252")
    she = w.template(sid, "Zoë".encode("cp1252"), male=False)
    he = w.template(sid, b"Tom", male=True)
    assert she == "Zoë : Elle va bien. Elle est prête.".encode("cp1252")
    assert he == "Tom : Il va bien. Il est prêt.".encode("cp1252")


def test_bad_lines_show_english_and_the_rest_still_work(exe, dll, table, entries):
    ok_k, ok_en = key(0x41A, table)
    sid_xy = first(table, lambda t: t == "%d of %d")
    xy_k, xy_en = key(sid_xy, table)
    long_sid = next(int(e.key.split("/")[1].split("~")[0]) for e in entries.values()
                    if e.max_length and e.max_length < 40 and len(e.english) > 3)
    long_k, long_en = key(long_sid, table)
    never_k, never_en = key(0x002, table)                                # the decimal point: never
    wrong_k = tfmt.make_key("strings", "1065", "Something else")         # the English changed since
    plain = first(table, lambda t: "{" not in t and "%" not in t and len(t) > 10, skip=(0x41A,))
    plain_k, plain_en = key(plain, table)
    rows = [
        (ok_k, ok_en, "Terminé"),
        (xy_k, xy_en, "%d sur %s"),                                      # a placeholder changed
        (long_k, long_en, "x" * 200),                                    # past its room
        (never_k, never_en, "Masculin"),                                 # (a decimal point is never)
        (wrong_k, "Something else", "Autre"),
        (plain_k, plain_en, "{il/elle} " + plain_en),                    # a person choice in a line nobody fills
    ]
    w, tf = world(exe, dll, rows)
    assert w.installed == 1
    assert w.get_string(0x41A) == "Terminé".encode("cp1252")
    for sid in (sid_xy, long_sid, 0x002, 1065, plain):
        assert w.get_string(sid) == table[sid][1].encode("cp1252"), sid
        assert w.translation_of(sid) == 0
    log = w.log()
    assert "5 line(s) show English" in log, log
    assert "Something else" not in log and "Masculin" not in log         # line numbers, never the text
    # the patcher's validator refuses the same lines
    report = tfmt.validate(tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1"), list(entries.values()))
    bad = {p.key for p in report.errors}
    assert {xy_k, long_k, plain_k, never_k} <= bad and ok_k not in bad
    assert wrong_k in report.english_changed                             # marked: "English changed"


@pytest.mark.parametrize("files", ["none", "english", "other game", "not utf8"])
def test_no_usable_choice_changes_nothing(exe, dll, table, files):
    import translations_emu as te
    k, en = key(0x41A, table)
    tf = tfmt.new_file("vf1", [tfmt.Entry(k, en)], "Test", "fr")
    tf.rows[0].translation = "Terminé"
    data = tfmt.to_bytes(tf)
    chosen = {
        "none": {},
        "english": {INI: b"\xef\xbb\xbflanguage=\r\n"},
        "other game": {INI: ini(), te.CHOSEN: data.replace(b"@game\tVirtual Families", b"@game\tFish Tycoon")},
        "not utf8": {INI: ini(), te.CHOSEN: b"Key\tEnglish\tTranslation\r\n\xff\xfe\xfd"},
    }[files]
    w = te.TranslationWorld(exe, dll, chosen)
    assert w.start() == 0
    assert w.get_string(0x41A) == b"Done"
    assert w.protect_calls == []                                          # nothing of the game's code was touched


def test_the_runtime_and_the_validator_use_the_same_lines(exe, dll, table, entries):
    """A file with every kind of line: the DLL uses exactly the ones the patcher's validator accepts."""
    picked = list(entries.values())[::23][:60]
    rows = []
    for n, e in enumerate(picked):
        variant = n % 5
        if variant == 0:
            tr = e.english.upper()
        elif variant == 1:
            tr = e.english + " " + "é" * 40
        elif variant == 2:
            tr = "{il/elle} " + e.english
        elif variant == 3:
            tr = e.english.replace("{name}", "{nom}")
        else:
            tr = "« " + e.english + " »"
        rows.append((e.key, e.english, tr))
    w, tf = world(exe, dll, rows)
    parsed = tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1")
    report = tfmt.validate(parsed, list(entries.values()))
    bad = {p.key for p in report.errors}
    want = {int(k.split("/")[1].split("~")[0]) for k, _en, tr in rows if tr and k not in bad}
    got = {int(k.split("/")[1].split("~")[0]) for k, _en, _tr in rows
           if w.translation_of(int(k.split("/")[1].split("~")[0]))}
    assert got == want
    assert 10 < len(got) < len(rows)


# ---------------------------------------------------------------------------------------------- room


def test_no_translation_ever_passes_the_room_the_game_gives_it(exe, dll, table, entries):
    """Every line at its room's end is used; one byte more is refused (English)."""
    sample = [e for e in entries.values() if e.max_length < vts.MAX_LINE][::9][:25]
    assert sample
    rows = [(e.key, e.english, "é" * (e.max_length // 2)) for e in sample]
    rows += [(e.key, e.english, "é" * (e.max_length // 2) + "xx") for e in sample]
    w, _tf = world(exe, dll, rows)
    for e in sample:
        sid = int(e.key.split("/")[1].split("~")[0])
        assert w.translation_of(sid), e.key                                   # the first (fits) counts
    w2, _tf = world(exe, dll, rows[len(sample):])
    for e in sample:
        sid = int(e.key.split("/")[1].split("~")[0])
        assert w2.translation_of(sid) == 0, e.key


def test_a_guarded_copy_never_holds_more_than_the_english(exe, dll, table, entries):
    """The calls whose line comes from data: a translated line reaching them is cut to its English length."""
    data = json.loads((ROOT / "data" / "vf1_translation_limits.json").read_text(encoding="utf-8"))
    assert len(data["unresolved"]) == 8
    roomy = next(e for e in entries.values() if e.max_length == vts.MAX_LINE and 6 < len(e.english) < 30
                 and "{" not in e.english and "%" not in e.english)
    sid = int(roomy.key.split("/")[1].split("~")[0])
    long_tr = "Ä" * 60
    w, _tf = world(exe, dll, [(roomy.key, roomy.english, long_tr)])
    out = w.translation_of(sid)
    assert w.e.read_cstr_bytes(out) == b"\xc4" * 60
    english_len = len(roomy.english)
    e = w.e
    for site in data["unresolved"]:
        call = int(site["call"], 16)
        dst = e.alloc(4096, fill=0xCC)
        if site["target"] == "0x4985BB":                        # sprintf(dst, "%s\n", line)
            fmt = e.alloc(8)
            e.write(fmt, b"%s\n\0")
            n = w.run_call(call, [dst, fmt, out])
            assert e.read_cstr_bytes(dst) == b"\xc4" * english_len + b"\n", site
            assert n == english_len + 1
        else:                                                  # strncpy / strncat(dst, line, 4000)
            e.write(dst, b"\0")
            w.run_call(call, [dst, out, 4000])
            assert e.read_cstr_bytes(dst) == b"\xc4" * english_len, site
    # a translated FORMAT (sprintf(dst, GetString(id), n) at 0x47A513, the id from a caller's table) makes at
    # most what the English format makes
    dst = e.alloc(256, fill=0xCC)
    assert w.run_call(0x47A513, [dst, out, 3]) == english_len
    assert e.read_cstr_bytes(dst) == b"\xc4" * english_len and e.read(dst + english_len + 1, 4) == b"\xCC" * 4
    fmt_sid = first(table, lambda t: t == "%d of %d")
    k, en = key(fmt_sid, table)
    w2, _tf = world(exe, dll, [(k, en, "%d / %d")])
    dst = w2.e.alloc(256, fill=0xCC)
    w2.run_call(0x47A513, [dst, w2.translation_of(fmt_sid), 3, 12])
    assert w2.e.read_cstr_bytes(dst) == b"3 / 12"
    w3, _tf = world(exe, dll, [(k, en, "%d sur %d")])                       # 9 letters: past its room (8)
    assert w3.translation_of(fmt_sid) == 0


def test_the_limits_are_the_vanilla_codes(exe):
    """data/vf1_translation_limits.json and native/vf1tr/vf1tr_limits.h are what the scan of the vanilla
    executable gives now (tools/build_vf1_translation_limits.py)."""
    pytest.importorskip("capstone")
    import build_vf1_translation_limits as bl
    data = bl.scan(exe.read_bytes())
    assert json.loads((ROOT / "data" / "vf1_translation_limits.json").read_text(encoding="utf-8")) == data
    assert (ROOT / "native" / "vf1tr" / "vf1tr_limits.h").read_text(encoding="utf-8") == bl.header(data)
    assert data["get_string_calls"] == 571 and data["copies"] == 390


# ---------------------------------------------------------------------------------------------- the patches' own text


def text_w(w, english: str) -> tuple[int, int, str]:
    """VF1Tr_TextW(english): (the pointer handed in, the pointer back, the text back)."""
    at = w.e.alloc(len(english) * 2 + 4)
    w.e.write(at, english.encode("utf-16-le") + b"\0\0")
    back = w.e.call(w.e.dll_export("VF1Tr_TextW"), (at,))
    return at, back, w.e.wstr(back)


def text_a(w, english: str, room: int) -> tuple[int, int, bytes]:
    at = w.e.alloc(len(english) + 4)
    w.e.write(at, english.encode("cp1252") + b"\0")
    back = w.e.call(w.e.dll_export("VF1Tr_TextA"), (at, room))
    return at, back, w.e.read_cstr_bytes(back)


@pytest.fixture(scope="module")
def patch():
    return {e.english: e for e in vts.patch_entries()}


def test_a_patchs_own_text_is_translated_by_its_english(exe, dll, table, patch, entries):
    """vf1fun.dll asks for its text by its English: the translation when there is one that fits, else the very
    pointer it handed in (its English). The validator accepts exactly the same lines."""
    money, food, movie, upgrades = (patch[t] for t in ("No Money", "Food now: %d", "Watching a movie", "Upgrades"))
    menu = patch["Upgrades Menu"]
    rows = [
        (money.key, money.english, "Plus d'argent"),
        (food.key, food.english, "Nourriture : %s"),                        # a placeholder changed: English
        (movie.key, movie.english, "Regarde un film"),
        (upgrades.key, upgrades.english, "Améliorations"),
        (menu.key, menu.english, "é" * (menu.max_length // 2 + 1)),         # past its room: English
    ]
    w, tf = world(exe, dll, rows)
    assert w.installed == 1, w.log()
    at, back, text = text_w(w, "No Money")
    assert text == "Plus d'argent" and back != at
    for english in ("Food now: %d", "Upgrades Menu", "Not a line of any patch"):
        at, back, text = text_w(w, english)
        assert back == at and text == english, english
    at, back, text = text_a(w, "Watching a movie", 39)
    assert text == "Regarde un film".encode("cp1252")
    assert text_a(w, "Upgrades", 60)[2] == "Améliorations".encode("cp1252")
    at, back, text = text_a(w, "Upgrades", 12)                              # its caller's room is 12: English
    assert back == at and text == b"Upgrades"
    report = tfmt.validate(tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1"), list(entries.values()))
    bad = {p.key for p in report.errors}
    assert bad == {food.key, menu.key}
    # with the Unicode settings the game draws UTF-8
    w2, _tf = world(exe, dll, rows, unicode_dll=True)
    assert text_a(w2, "Upgrades", 60)[2] == "Améliorations".encode("utf-8")
    assert text_w(w2, "No Money")[2] == "Plus d'argent"


def test_a_patchs_text_with_any_letter_and_at_its_room(exe, dll, patch):
    e = patch["Max happiness"]
    fits = "😀" * (e.max_length // 4)                                         # 4 UTF-8 bytes each, a surrogate pair
    w, _tf = world(exe, dll, [(e.key, e.english, fits)])
    assert text_w(w, "Max happiness")[2] == fits
    w2, _tf = world(exe, dll, [(e.key, e.english, fits + "x" * 4)])
    assert text_w(w2, "Max happiness")[2] == "Max happiness"


def test_nothing_chosen_every_patch_line_is_its_english(exe, dll):
    import translations_emu as te
    w = te.TranslationWorld(exe, dll, {})
    assert w.start() == 0
    at, back, text = text_w(w, "No Money")
    assert back == at
    at, back, text = text_a(w, "Upgrades", 60)
    assert back == at


def test_the_family_history_words_are_translated_on_screen_and_english_for_the_log(exe, dll, table):
    """"Male", the causes of death, "New Generation"... are translated in the game; vf1logs.dll asks
    VF1Tr_English for the log, and VF1Tr_EnglishOf gives the English of a title the game showed translated."""
    male_k, male_en = key(0x464, table)
    done_k, done_en = key(0x41A, table)
    cause_k, cause_en = key(0x508, table)
    w, _tf = world(exe, dll, [(male_k, male_en, "Masc"), (done_k, done_en, "Terminé"), (cause_k, cause_en, "Vieillesse")])
    assert w.get_string(0x464) == b"Masc" and w.get_string(0x508) == b"Vieillesse"
    english = w.e.dll_export("VF1Tr_English")
    assert w.e.read_cstr_bytes(w.e.call(english, (0x464,))) == b"Male"
    assert w.e.read_cstr_bytes(w.e.call(english, (0x508,))) == cause_en.encode("cp1252")
    assert w.e.call(english, (0,)) == 0
    english_of = w.e.dll_export("VF1Tr_EnglishOf")
    shown = w.translation_of(0x41A)
    assert w.e.read_cstr_bytes(w.e.call(english_of, (shown,))) == b"Done"
    copy = w.e.alloc(16)
    w.e.write(copy, "Terminé".encode("cp1252") + b"\0")                    # the same text in a dialog's buffer
    assert w.e.read_cstr_bytes(w.e.call(english_of, (copy,))) == b"Done"
    other = w.e.alloc(16)
    w.e.write(other, b"A name\0")
    assert w.e.call(english_of, (other,)) == other


def test_the_likes_lists_keep_every_item_each_no_longer(exe, dll, table, entries):
    k, en = key(0x45B, table)
    items = en.split(",")
    same = ",".join(i[: max(1, len(i) - 1)] for i in items)                 # each item one letter shorter
    fewer = ",".join(items[:-1])
    longer = ",".join(items[:-1] + [items[-1] + "xx"])
    entry = entries[k]
    assert entry.items and "items" in entry.notes
    for tr, used in ((same, True), (fewer, False), (longer, False)):
        w, tf = world(exe, dll, [(k, en, tr)])
        assert bool(w.translation_of(0x45B)) == used, tr
        report = tfmt.validate(tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1"), list(entries.values()))
        assert (k in {p.key for p in report.errors}) == (not used), tr
    dk, den = key(0x45C, table)
    assert entries[dk].items


# ---------------------------------------------------------------------------------------------- percent signs

PERCENTS = ("2 %", "2 %", "2 %", "50 % de réduction")


def real_sprintf(fmt: bytes, *numbers: int) -> bytes:
    """The C runtime's own sprintf (msvcrt), on the bytes the DLL hands the game."""
    import ctypes
    buf = ctypes.create_string_buffer(1024)
    ctypes.cdll.msvcrt.sprintf(buf, fmt, *(ctypes.c_int(n) for n in numbers))
    return buf.value


def real_swprintf(fmt: str, *numbers: int) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.cdll.msvcrt.swprintf(buf, fmt, *(ctypes.c_int(n) for n in numbers))
    return buf.value


@pytest.mark.parametrize("text", PERCENTS)
def test_a_percent_sign_in_a_game_format_line_shows_one_percent(exe, dll, table, entries, text):
    """eString_ReportSalary "$%d/day. Has $%d in the bank." is a format the game hands sprintf: a French "2 %" is
    handed on as "2 %%" (the space flag never reads it as "% d"), and formatting shows a single '%'. The validator
    accepts it, and the escaped bytes count toward the room."""
    k, en = key(59, table)
    assert entries[k].is_format
    translation = f"$%d/j;{text};$%d"                                                 # at most 29 bytes as handed on
    w, tf = world(exe, dll, [(k, en, translation)], unicode_dll=True)
    held = w.get_string(59)
    assert held == f"$%d/j;{text.replace('%', '%%')};$%d".encode("utf-8")
    assert real_sprintf(held, 5, 100) == f"$5/j;{text};$100".encode("utf-8")         # the real formatter
    dst = w.e.alloc(256, fill=0xCC)                                                     # the game's guarded sprintf
    w.run_call(0x47A513, [dst, w.translation_of(59), 5, 100])
    assert w.e.read_cstr_bytes(dst) == f"$5/j;{text};$100".encode("utf-8")
    report = tfmt.validate(tfmt.parse_text(tfmt.to_bytes(tf).decode("utf-8-sig"), "vf1"), list(entries.values()))
    assert k not in {p.key for p in report.errors}


@pytest.mark.parametrize("text", PERCENTS)
def test_a_percent_sign_in_a_line_that_is_no_format_shows_unchanged(exe, dll, table, entries, text):
    """eString_CurrentInterestRateLabel ("Current Interest Rate: %") is only shown: its translation is handed on
    as it is, a single '%'."""
    k, en = key(38, table)
    assert entries[k].is_format is False
    w, _tf = world(exe, dll, [(k, en, f"Taux : {text}")], unicode_dll=True)
    assert w.get_string(38) == f"Taux : {text}".encode("utf-8")


def test_the_escaped_percent_counts_toward_the_room(exe, dll, table, entries):
    """eString_XofY "%d of %d" has 8 bytes: "%d/%d 9%" is 8 as written but 9 as handed to sprintf ("9%%"): English."""
    k, en = key(460, table)
    assert entries[k].max_length == 8
    w, tf = world(exe, dll, [(k, en, "%d/%d %")])
    assert w.get_string(460) == b"%d/%d %%"                                             # 8 bytes: fits
    w2, tf2 = world(exe, dll, [(k, en, "%d/%d 9%")])
    assert w2.translation_of(460) == 0 and w2.get_string(460) == b"%d of %d"
    report = tfmt.validate(tfmt.parse_text(tfmt.to_bytes(tf2).decode("utf-8-sig"), "vf1"), list(entries.values()))
    assert k in {p.key for p in report.errors}


@pytest.mark.parametrize("text", PERCENTS)
def test_a_percent_sign_in_a_patch_line(exe, dll, patch, text):
    """vf1fun.dll's "Food now: %d" is swprintf's format: VF1Tr_TextW hands "%%", which the real swprintf shows as one
    '%'; "Interest rate %" is only shown: unchanged."""
    food, rate = patch["Food now: %d"], patch["Interest rate %"]
    assert food.is_format and not rate.is_format
    w, _tf = world(exe, dll, [(food.key, food.english, f"Nourriture : %d ({text})"),
                              (rate.key, rate.english, f"Taux : {text}")])
    shown = text_w(w, "Food now: %d")[2]
    assert shown == f"Nourriture : %d ({text.replace('%', '%%')})"
    assert real_swprintf(shown, 7) == f"Nourriture : 7 ({text})"
    assert text_w(w, "Interest rate %")[2] == f"Taux : {text}"
