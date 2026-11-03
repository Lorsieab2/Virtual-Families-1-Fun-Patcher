"""The translation file format v1 (patcher/translation_format.py) and Virtual Families 1's line inventory
(patcher/vf1_translation_strings.py): reading, writing, placeholders, choices (the game's own {he/she} too),
plurals, escapes, BOMs, UTF-16, fallbacks, email refusal with its line number, updates and coverage.  Ported from
the Fish and Plant Tycoon Fix Patcher's tests/test_translation_format.py."""

from __future__ import annotations

import os
from pathlib import Path
import re
import unittest

import pytest

import translation_format as tf
import vf1_translation_strings as ts

ENTRIES = [
    tf.Entry(tf.make_key("strings", "1", "Age: "), "Age: "),
    tf.Entry(tf.make_key("strings", "69", "You have sold %d fish!"), "You have sold %d fish!", "%1 = number"),
    tf.Entry(tf.make_key("mod", "x.title", "Title"), "Title", max_length=8),
]


def sample(translations=("Âge : ", "Vous avez vendu %d {%1: one=poisson | other=poissons} !", "")) -> tf.TranslationFile:
    f = tf.new_file("vf1", ENTRIES, "Français", "fr", "Someone")
    for row, text in zip(f.rows, translations):
        row.translation = text
    return f


class Keys(unittest.TestCase):
    def test_key_is_source_id_and_the_hash_of_the_english(self) -> None:
        key = tf.make_key("strings", "69", "You have sold %d fish!")
        self.assertRegex(key, r"^strings/69~[0-9a-f]{8}$")
        self.assertEqual(key[-8:], __import__("hashlib").sha256(b"You have sold %d fish!").hexdigest()[:8])
        self.assertEqual(tf.split_key(key), ("strings", "69", key[-8:]))
        self.assertIsNone(tf.split_key("Strings/69~12345678"))
        self.assertIsNone(tf.split_key("strings/69~1234567"))
        self.assertEqual(tf.base_key(key), "strings/69")
        with self.assertRaises(ValueError):
            tf.make_key("bad source", "1", "x")


class Escapes(unittest.TestCase):
    def test_round_trip(self) -> None:
        for text in ("a\nb", "tab\there", "back\\slash", "\\n literal", "end\\", "x\\|y", "\r\nwin"):
            self.assertEqual(tf.decode_escapes(tf.encode_escapes(text)), text.replace("\r\n", "\n"))
        self.assertEqual(tf.decode_escapes("a\\qb"), "a\\qb")              # any other backslash is kept

    def test_quoted_fields(self) -> None:
        f = sample(('"quoted" start', "", ""))
        text = tf.to_text(f)
        self.assertIn('"""quoted"" start"', text)
        self.assertEqual(tf.parse_text(text).rows[0].translation, '"quoted" start')


class Reading(unittest.TestCase):
    def test_round_trip_with_bom_and_crlf(self) -> None:
        data = tf.to_bytes(sample())
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", data)
        parsed = tf.parse_bytes(data, "vf1")
        self.assertEqual(parsed.problems, [])
        self.assertEqual(parsed.language, "Français")
        self.assertEqual(parsed.code, "fr")
        self.assertEqual(parsed.translator, "Someone")
        self.assertEqual(len(parsed.translations()), 2)
        self.assertEqual(tf.to_bytes(parsed), data)                          # comments and order kept

    def test_utf8_without_bom_and_utf16(self) -> None:
        text = tf.to_text(sample())
        for data in (text.encode("utf-8"), b"\xff\xfe" + text.encode("utf-16-le"), b"\xfe\xff" + text.encode("utf-16-be")):
            parsed = tf.parse_bytes(data, "vf1")
            self.assertEqual(parsed.fatal, "")
            self.assertEqual(len(parsed.translations()), 2)

    def test_other_encodings_are_refused_as_a_whole(self) -> None:
        parsed = tf.parse_bytes(tf.to_text(sample()).encode("cp1252"), "vf1")
        self.assertIn("not UTF-8", parsed.fatal)
        self.assertEqual(parsed.translations(), {})

    def test_header_game_and_format(self) -> None:
        self.assertIn("header", tf.parse_text("strings/1~4ece2634\tAge: \tx\n").fatal)
        other = tf.to_bytes(sample()).replace(b"@game\tVirtual Families", b"@game\tFish Tycoon")
        self.assertIn("not Virtual Families", tf.parse_bytes(other, "vf1").fatal)
        f = sample()
        f.set_info("@format", "2", "2")
        self.assertIn("newer", tf.parse_bytes(tf.to_bytes(f), "vf1").fatal)
        f.set_info("@format", "1.4", "1.4")
        self.assertEqual(tf.parse_bytes(tf.to_bytes(f), "vf1").fatal, "")

    def test_fullwidth_at_sign_info_rows(self) -> None:
        text = tf.to_text(sample()).replace("@language", "＠language")
        self.assertEqual(tf.parse_text(text, "vf1").language, "Français")

    def test_bad_rows_fall_back_and_name_their_line(self) -> None:
        text = tf.to_text(sample(("Âge : {x}", "Vous avez vendu %s !", "")))
        parsed = tf.parse_text(text, "vf1")
        lines = text.split("\r\n")
        bad = {p.line for p in parsed.errors}
        self.assertEqual(bad, {n for n, l in enumerate(lines, 1) if l.startswith(("strings/1~", "strings/69~"))})
        self.assertEqual(parsed.translations(), {})

    def test_edited_english_and_duplicate_and_bad_key(self) -> None:
        text = tf.to_text(sample()).replace("\tAge: \t", "\tAge:\t")
        parsed = tf.parse_text(text, "vf1")
        self.assertTrue(any("does not match the key" in p.message for p in parsed.errors))
        row = [l for l in tf.to_text(sample()).split("\r\n") if l.startswith("strings/1~")][0]
        parsed = tf.parse_text(tf.to_text(sample()) + row + "\r\nnot a key\tx\ty\r\nnocolumns\r\n", "vf1")
        messages = " ".join(p.message for p in parsed.errors)
        self.assertIn("already on line", messages)
        self.assertIn("not a valid key", messages)
        self.assertIn("no tab-separated columns", messages)

    def test_columns_after_notes_and_comments_are_kept(self) -> None:
        text = tf.to_text(sample()).replace("\tAge: \tÂge : ", "\tAge: \tÂge : \tmy note\textra")
        parsed = tf.parse_text(text, "vf1")
        self.assertEqual(parsed.rows[0].notes, "my note")
        self.assertEqual(parsed.rows[0].extra, ["extra"])
        self.assertIn("my note\textra", tf.to_text(parsed))


class Placeholders(unittest.TestCase):
    def check(self, english, translation, code="fr"):
        return tf.check_translation(english, translation, code)

    def test_printf_same_conversions_same_order(self) -> None:
        self.assertEqual(self.check("%s has %d", "%s a %d")[0], [])
        self.assertEqual(self.check("%d", "%3d")[0], [])                  # width may change
        self.assertEqual(self.check("%d", "%i")[0], [])
        self.assertTrue(self.check("%s has %d", "%d a %s")[0])
        self.assertTrue(self.check("%d", "")[0] == [])                    # empty: untranslated, not an error
        self.assertTrue(self.check("%d", "rien")[0])
        self.assertEqual(self.check("%d", "%d 50%")[0], [])               # a lone %: plain text
        self.assertTrue(self.check("%d", "%d 50%%")[1])                   # "%%" would show two: a warning
        self.assertEqual(self.check("%d", "%d %n")[0], [])                # no token of the English: plain text
        self.assertEqual(tf.runtime_text("%d %n", "%d", True), "%d %%n")  # ... handed to printf as "%%n"
        self.assertEqual(self.check("%d%%", "%d %%")[0], [])               # the English's own "%%"
        self.assertEqual(self.check("Save 50%! %d", "50% !%d")[0], [])
        self.assertEqual(self.check("50% of %d", "50 % de %d")[0], [])     # "% d" is no token of the English
        self.assertTrue(self.check("%d of %d", "%d sur % d")[0])           # "% d" is not the English's "%d"

    def test_named_variables_any_order(self) -> None:
        self.assertEqual(self.check("{a} and {b}", "{b} et {a}")[0], [])
        self.assertTrue(self.check("{a} and {b}", "{a}")[0])
        self.assertTrue(self.check("{a}", "{a} {c}")[0])
        self.assertEqual(self.check("x", "{{literal}}")[0], [])

    def test_selects(self) -> None:
        eng = "You have sold %d fish!"
        ok = "%d {%1: one=poisson | other=poissons}"
        self.assertEqual(self.check(eng, ok)[0], [])
        self.assertTrue(self.check(eng, "%d {%1: m=il | f=elle}")[0])      # a number needs number keys
        self.assertTrue(self.check(eng, "%d {%2: one=a}")[0])              # no such placeholder
        self.assertTrue(self.check(eng, "%d {count: one=a}")[0])           # undeclared subject
        self.assertTrue(self.check(eng, "%d {%1: one=a %d}")[0])           # printf inside a branch
        self.assertTrue(self.check(eng, "%d {%1: one={%1: one=x}}")[0])    # nested
        self.assertTrue(self.check(eng, "%d {%1: one=a | bogus=b}")[0])
        self.assertTrue(self.check(eng, "%d {%1: one=a")[0])               # unbalanced
        self.assertTrue(self.check("%s", "%s {%1: m=a | f=b}")[0])         # a text is not a person here
        self.assertEqual(self.check(eng, "%d {%1: =0=aucun | one=un | other=plusieurs}")[0], [])
        warnings = self.check(eng, "%d {%1: one=a | few=b | other=c}", "fr")[1]
        self.assertTrue(any("no 'few' form" in w for w in warnings))

    def test_evaluate_and_fallbacks(self) -> None:
        text = "%d {%1: =0=aucun | one=un | other=plusieurs} {%1: one=a\\|b | other=c}"
        self.assertEqual(tf.evaluate(text, "fr", {"%1": 0}), "%d aucun a|b")
        self.assertEqual(tf.evaluate(text, "fr", {"%1": 1}), "%d un a|b")
        self.assertEqual(tf.evaluate(text, "fr", {"%1": 9}), "%d plusieurs c")
        self.assertEqual(tf.evaluate(text, "fr"), "%d plusieurs c")         # unknown number: other
        person = "{%1: m=Il | f=Elle | o=Iel} {%1: m=x | f=y}"
        self.assertEqual(tf.evaluate(person, "fr", sexes={"%1": "f"}), "Elle y")
        self.assertEqual(tf.evaluate(person, "fr"), "Iel x")               # o, then the first branch
        self.assertEqual(tf.evaluate("{%1: one=a | few=b}", "pl", {"%1": 7}), "a")   # no many/other: the first
        self.assertEqual(tf.evaluate("{{x}} {%1: one={{y}}}", "en", {"%1": 1}), "{x} {y}")

    def test_plural_rules(self) -> None:
        cases = {
            "en": {0: "other", 1: "one", 2: "other"},
            "fr": {0: "one", 1: "one", 2: "other", 1_000_000: "many"},
            "ru": {1: "one", 21: "one", 2: "few", 22: "few", 5: "many", 11: "many", 12: "many", 111: "many"},
            "pl": {1: "one", 2: "few", 5: "many", 22: "few", 21: "many"},
            "ar": {0: "zero", 1: "one", 2: "two", 3: "few", 11: "many", 100: "other"},
            "ja": {1: "other", 2: "other"}, "zh-Hans": {1: "other"}, "tr": {1: "one", 2: "other"},
            "cs": {1: "one", 3: "few", 5: "other"}, "lv": {0: "zero", 1: "one", 2: "other"},
            "pt": {0: "one", 1: "one"}, "pt-PT": {0: "other", 1: "one"}, "xx": {1: "one", 2: "other"},
        }
        for code, expected in cases.items():
            for n, category in expected.items():
                self.assertEqual(tf.plural_category(code, n), category, (code, n))
        self.assertEqual(tf.plural_categories("ru"), ("one", "few", "many"))
        self.assertEqual(tf.plural_categories("ja"), ("other",))


class Emails(unittest.TestCase):
    def test_any_email_like_text_is_refused_with_its_line(self) -> None:
        for email in ("someone@example.com", "first.last+tag@sub.example.co.uk", "me＠example.org",
                      "me [at] example [dot] com", "me (at) example.com", "me at example dot com"):
            f = sample()
            f.set_info("@translator", "", "Ann " + email)
            text = tf.to_text(f)
            parsed = tf.parse_text(text, "vf1")
            line = next(n for n, l in enumerate(text.split("\r\n"), 1) if l.startswith("@translator"))
            emails = [p for p in parsed.errors if tf.EMAIL_MESSAGE in p.message]
            self.assertEqual([p.line for p in emails], [line], email)
            self.assertFalse(tf.validate(parsed).usable)
            self.assertNotIn(email, str(emails[0]))                        # never repeated back
        for text in ("# contact x@y.com", "strings/1~4ece2634\tAge: \tmail a@b.fr"):
            parsed = tf.parse_text(tf.to_text(sample()) + text + "\r\n", "vf1")
            self.assertTrue(any(tf.EMAIL_MESSAGE in p.message for p in parsed.errors))

    def test_ordinary_text_is_not_an_email(self) -> None:
        for text in ("@format", "Price: $ %i", "Fish & Plant @ home", "50% at most", "user@localhost",
                     "Try Plant Tycoon at LDW.com!"):
            self.assertFalse(tf.contains_email(text), text)


class Coverage(unittest.TestCase):
    def test_validate_against_the_inventory(self) -> None:
        f = sample(("Âge : ", "", "Un très long titre"))
        report = tf.validate(tf.parse_bytes(tf.to_bytes(f), "vf1"), ENTRIES)
        self.assertEqual((report.translated, report.total), (1, 3))
        self.assertAlmostEqual(report.coverage, 100 / 3)
        self.assertTrue(any("too long" in p.message for p in report.errors))
        self.assertIn("Coverage: 1 of 3", report.summary())

    def test_update_marks_new_lines_and_keeps_old_translations(self) -> None:
        f = sample(("Âge : ", "Vendu %d", ""))
        newer = [ENTRIES[0], tf.Entry(tf.make_key("strings", "69", "You sold %d fish!"), "You sold %d fish!"),
                 tf.Entry(tf.make_key("strings", "2", "Status: "), "Status: ")]
        report = tf.update_to_inventory(f, newer)
        self.assertEqual(report.added, [newer[2].key])
        self.assertEqual(report.changed, [newer[1].key])
        self.assertIn(ENTRIES[2].key, report.unknown)
        keys = [r.key for r in f.rows]
        self.assertEqual(keys[:3], [newer[0].key, newer[1].key, ENTRIES[1].key])   # the old line kept after it
        reread = tf.parse_bytes(tf.to_bytes(f), "vf1")
        valid = tf.validate(reread, newer)
        self.assertEqual(valid.translated, 1)
        self.assertEqual(valid.english_changed, [ENTRIES[1].key])
        self.assertEqual(reread.translations()[ENTRIES[0].key], "Âge : ")

    def test_file_names(self) -> None:
        self.assertEqual(tf.file_name("Virtual Families", "日本語"), "Virtual Families - 日本語.txt")
        self.assertEqual(tf.file_name("Virtual Families", 'a/b:c'), "Virtual Families - a_b_c.txt")


class VirtualFamilies(unittest.TestCase):
    """The game's own fillers: {name}, {name2}, {award} and the person choice {he/she} / {his/2/her}."""

    def check(self, english, translation):
        return tf.check_translation(english, translation, "fr")[0]

    def test_the_games_person_choice(self) -> None:
        eng = "{name} is sick. {He/She} needs a doctor."
        self.assertEqual(self.check(eng, "{name} est malade. {Il/Elle} a besoin d'un médecin."), [])
        self.assertEqual(self.check(eng, "{name} est {name: m=malade | f=malade}."), [])
        self.assertEqual(self.check(eng, "{name} : {il/2/elle}"), [])                 # the second person
        self.assertTrue(self.check(eng, "{nom} est malade."))                        # {name} must stay
        self.assertTrue(self.check(eng, "{name} {name: one=a | other=b}"))           # a person, not a number
        self.assertTrue(self.check(eng, "{name} {name: m=a/b | f=c}"))               # the game splits at '/'
        self.assertTrue(self.check(eng, "{name} {name: o=x}"))                       # the game knows m and f
        self.assertTrue(self.check("Done", "{il/elle}"))                             # a line the game does not fill
        self.assertTrue(self.check("Done", "{name: m=a | f=b}"))
        self.assertEqual(self.check("You won {award} coins", "{award} {award: one=pièce | other=pièces}"), [])

    def test_what_the_game_is_handed(self) -> None:
        text = "{name} est {name: m=prêt | f=prête}, {name2: m=lui | f=elle} {Il/Elle} {award: one=a | other=b} {{x}}"
        self.assertEqual(tf.game_text(text), "{name} est {prêt/prête}, {lui/2/elle} {Il/Elle} b {x}")
        self.assertEqual(tf.evaluate("{Il/Elle} {il/2/elle}", sexes={"name": "f", "name2": "m"}), "Elle il")
        self.assertEqual(tf.measure("{il/elle}"), len("{il/elle}"))
        self.assertEqual(tf.measure("{name: m=a | f=bbbbbbbbbbbbbbbb}"), len("{a/bbbbbbbbbbbbbbbb}"))

    def test_room(self) -> None:
        self.assertFalse(tf.too_long("é" * 10, 20))
        self.assertTrue(tf.too_long("é" * 10 + "x", 20))                             # an accented letter is 2


def vanilla_exe() -> Path | None:
    folder = os.environ.get("VF1_VANILLA_DIR")
    path = Path(folder) / "Virtual Families.exe" if folder else None
    return path if path and path.is_file() else None


def test_the_inventory_is_the_games_string_table():
    exe = vanilla_exe()
    if exe is None:
        pytest.skip("set VF1_VANILLA_DIR to a copy of the vanilla Virtual Families folder")
    table = ts.read_table(exe.read_bytes())
    entries = [e for e in ts.entries_for(exe.read_bytes()) if e.key.startswith("strings/")]
    assert ts.entries_for(exe.read_bytes())[len(entries):] == ts.patch_entries()      # the patches' lines after
    assert len(table) == 1643
    assert table[0x41A] == ("eSayDone", "Done")
    ids = {int(e.key.split("/")[1].split("~")[0]) for e in entries}
    assert not ids & set(ts.limits()["never"])                                      # only the decimal point
    assert 0x41A in ids and len(entries) > 1600
    for e in entries:
        assert tf.split_key(e.key) and e.key.endswith(tf.key_hash(e.english))
        assert e.max_length <= ts.MAX_LINE
        assert e.max_length >= len(e.english.encode("utf-8")) or e.max_length == ts.room(
            int(e.key.split("/")[1].split("~")[0]), e.english)
    caption = next(e for e in entries if e.key.startswith("strings/401~"))
    assert caption.max_length == 38 and "at most 38 letters" in caption.notes   # strncpy(villager + 0x13594, .., 0x27)
    # a template made from it reads back with every line untranslated and no problem
    f = tf.new_file("vf1", entries, "Français", "fr")
    parsed = tf.parse_bytes(tf.to_bytes(f), "vf1")
    assert parsed.errors == []
    report = tf.validate(parsed, entries)
    assert report.total == len(entries) and report.translated == 0


def test_a_file_that_is_not_the_game_is_refused(tmp_path):
    with pytest.raises(ts.StringsError):
        ts.read_table(b"MZ" + b"\0" * 200)
    assert ts.find_vanilla_exe([tmp_path]) is None


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------------------------- Unicode 18.0


def _every_code_point(step: int = 1):
    """Every Unicode scalar value a translation may hold as text: all of planes 0-16 but the surrogates, the
    controls and the characters the format itself gives a meaning ({ } % \\ @ and the full-width at sign)."""
    special = set(map(ord, "{}%\\@＠  "))
    for cp in range(0x20, 0x110000, step):
        if 0xD800 <= cp <= 0xDFFF or cp in special or 0x7F <= cp <= 0x9F:
            continue
        yield chr(cp)


def test_every_unicode_18_code_point_is_accepted():
    """The owner: support the whole Unicode 18.0 chart collection. Nothing in the validator, the file format or
    the template checks a character's Unicode category, so a code point Python's own unicodedata does not know
    yet is accepted like any other: every scalar value is, assigned or not."""
    import unicodedata
    text = "".join(_every_code_point())
    unknown = [c for c in text if unicodedata.category(c) == "Cn"]
    assert len(unknown) > 800_000                                          # far more than Unicode 18.0 assigns
    size = 4000
    count = (len(text) + size - 1) // size
    entries = [tf.Entry(tf.make_key("strings", str(n), f"Line {n}"), f"Line {n}") for n in range(1, count + 1)]
    f = tf.new_file("vf1", entries, "Test", "und")
    for n, row in enumerate(f.rows):
        row.translation = text[n * size:(n + 1) * size]
        errors, _warnings = tf.check_translation(row.english, row.translation, "und")
        assert errors == [], (hex(ord(row.translation[0])), errors)
    back = tf.parse_bytes(tf.to_bytes(f), "vf1")
    assert not back.fatal
    assert [r.translation for r in back.rows] == [r.translation for r in f.rows]
    report = tf.validate(back, entries)
    assert report.errors == [] and report.translated == len(entries)


def test_code_points_new_in_unicode_17_and_18_are_kept_exactly():
    # Code points Python's unicodedata may still call unassigned, from blocks Unicode 17.0 and 18.0 fill (Sidetic
    # U+10940, Tangut Components Supplement U+18D80, CJK Extension J U+323B0 ...), and a grapheme cluster with a
    # combining mark and ZWJ sequences: written, read back and checked unchanged.
    sample = "\U00010940\U00010941\U00018D80\U000323B0\U0001CEC0́‍\U0001FAE9\U0001F9D1‍\U0001F9B0"
    f = tf.new_file("vf1", [tf.Entry(tf.make_key("strings", "1", "Done"), "Done")], "Test", "und")
    f.rows[0].translation = sample
    assert tf.check_translation("Done", sample, "und")[0] == []
    back = tf.parse_bytes(tf.to_bytes(f), "vf1")
    assert back.rows[0].translation == sample
    assert tf.measure(sample) == len(sample.encode("utf-8"))


# ---------------------------------------------------------------------------------------------- lists


def test_a_list_keeps_every_item_each_no_longer():
    english = "Running,Swimming,Reading"
    assert not tf.items_problem(english, "Courir,Nager,Lire")
    assert tf.items_problem(english, "Courir,Nager")                       # an item less
    assert tf.items_problem(english, "Courir,Nager,Lire,Danser")           # an item more
    assert tf.items_problem(english, "Faire du jogging,Nager,Lire")        # longer than "Running"
    entry = tf.Entry(tf.make_key("strings", "1115", english), english, items=True)
    f = tf.new_file("vf1", [entry], "Test", "fr")
    f.rows[0].translation = "Courir,Nager"
    report = tf.validate(f, [entry])
    assert report.errors and tf.ITEMS_MESSAGE in report.errors[0].message
    f.rows[0].translation = "Courir,Nager,Lire"
    assert tf.validate(f, [entry]).errors == []


# ---------------------------------------------------------------------------------------------- percent signs


FRENCH_PERCENTS = ("2 %", "2\u00a0%", "2\u202f%", "50 % de réduction")


@pytest.mark.parametrize("text", FRENCH_PERCENTS)
@pytest.mark.parametrize("is_format", [False, None])
def test_french_percent_signs_are_plain_text(text, is_format):
    """Only the English's own tokens are placeholders: "% d" in "50 % de" is plain text, not the space flag."""
    errors, warnings = tf.check_translation("%d of %d", f"%d sur %d, {text}", "fr", is_format=True)
    assert errors == [] and warnings == []
    errors, _w = tf.check_translation("Sale: 50% off", f"Soldes : {text}", "fr", is_format=is_format)
    assert errors == []


@pytest.mark.parametrize("text", FRENCH_PERCENTS)
def test_a_format_line_hands_printf_a_double_percent_and_shows_one(text):
    """In a printf FORMAT line every plain '%' is written "%%", so the real formatter shows a single '%'."""
    english = "Interest: %d"
    translation = f"Intérêt : %d ({text})"
    runtime = tf.runtime_text(translation, english, True)
    assert runtime == f"Intérêt : %d ({text.replace('%', '%%')})"
    shown = runtime.replace("%d", "{}", 1).replace("%%", "%").format(7)     # what printf("%d", 7) makes
    assert shown == f"Intérêt : 7 ({text})"
    import ctypes
    import ctypes.util
    if os.name == "nt":                                                     # the C runtime's own formatter
        buf = ctypes.create_unicode_buffer(256)
        ctypes.cdll.msvcrt.swprintf(buf, runtime, ctypes.c_int(7))
        assert buf.value == f"Intérêt : 7 ({text})"


@pytest.mark.parametrize("text", FRENCH_PERCENTS)
def test_a_line_that_is_no_format_is_handed_on_unchanged(text):
    translation = f"Soldes : {text}"
    assert tf.runtime_text(translation, "Sale: 50% off", False) == translation
    assert tf.game_text(translation, "Sale: 50% off", False) == translation


def test_the_extra_percent_bytes_count_toward_the_room():
    english = "%d off"
    assert tf.measure("%d 5 %", english=english, is_format=True) == len("%d 5 %%")
    assert tf.measure("%d 5 %", english=english, is_format=False) == len("%d 5 %")
    assert not tf.too_long("%d 5 %", 7, english=english, is_format=True)
    assert tf.too_long("%d 5 %", 6, english=english, is_format=True)        # 7 bytes as handed to printf
    entry = tf.Entry(tf.make_key("strings", "460", english), english, max_length=6, is_format=True)
    f = tf.new_file("vf1", [entry], "Français", "fr")
    f.rows[0].translation = "%d 5 %"
    report = tf.validate(tf.parse_bytes(tf.to_bytes(f), "vf1"), [entry])
    assert any("too long" in p.message for p in report.errors)


def test_the_format_lines_come_from_the_programs_own_calls():
    """A game line the game hands sprintf as its format, and a patch line vf1fun.dll hands swprintf as its format,
    are formats; a line with a percent sign it only shows is not."""
    assert ts.is_format_key(tf.make_key("strings", "460", "%d of %d")) is True          # eString_XofY
    assert ts.is_format_key(tf.make_key("strings", "1323", "x")) is None                # no format: its English decides
    patch = {e.english: e for e in ts.patch_entries()}
    assert patch["Food now: %d"].is_format is True
    assert patch["Money now: $%.0f        Interest rate now: %.1f%%"].is_format is True
    assert patch["There is no family yet."].is_format is True                           # swprintf(s, 200, TR(...))
    broker = next(e for t, e in patch.items() if t.startswith("Upgrade your broker"))
    assert broker.is_format is False
    assert ts.is_format_key(broker.key) is False and ts.is_format_key("other/x~12345678") is None
    # "% d" in "50% discount" is no placeholder of a line that is no format
    csa = next(e for t, e in patch.items() if "50% discount" in t)
    assert tf.check_translation(csa.english, "Un abonnement : 50 % de réduction.", "fr", is_format=False)[0] == []
