"""The one rule for text in Virtual Families 1's saves and logs (patcher/vf1_text.py), shared by every reader and
by vf1text.dll (Render Unicode with In-Game Fonts)."""
import subprocess
import sys

import pytest

from conftest import ROOT

import vf1_text as t


@pytest.mark.parametrize("data,text", [
    (b"Smith", "Smith"),
    (b"Zo\xc3\xab", "Zoë"),                               # UTF-8
    (b"Caf\xe9", "Café"),                                 # not UTF-8: one byte, one character
    (b"\x93Quote\x94 \x80", "“Quote” €"),       # Windows-1252
    (b"x\x81y", "x\x81y"),                                     # an unassigned byte stays Latin-1
    (b"\xc3", "Ã"),                                       # a cut sequence is not UTF-8
    (b"\xc0\xaf", "À¯"),                             # an overlong form is not UTF-8
    (b"\xed\xa0\x80", "í €"),                   # nor is a surrogate
    (b"\xf0\x92\x80\xad", "\U0001202d"),                       # four bytes: Cuneiform
    (b"Name\0garbage", "Name"),                                # up to the NUL
])
def test_decode(data, text):
    assert t.decode(data) == text


def test_ascii_is_unchanged_and_utf8_round_trips():
    for text in ["Smith", "Zoë", "İlkay Ğul", "日本", "\U0001202d\U0001f44d\U0001f3fd"]:
        assert t.decode(t.encode(text)) == text
    assert t.encode("Smith") == b"Smith"
    with pytest.raises(ValueError):
        t.encode("a\0b")


@pytest.mark.parametrize("text,clusters", [
    ("abc", ["a", "b", "c"]),
    ("éx", ["é", "x"]),                                       # a letter and its accent
    ("\U0001f44d\U0001f3fd!", ["\U0001f44d\U0001f3fd", "!"]),            # skin tone
    ("\U0001f468‍\U0001f469‍\U0001f467", ["\U0001f468‍\U0001f469‍\U0001f467"]),   # ZWJ family
    ("\U0001f1eb\U0001f1f7\U0001f1e9\U0001f1ea", ["\U0001f1eb\U0001f1f7", "\U0001f1e9\U0001f1ea"]),   # two flags
    ("❤️", ["❤️"]),                                   # variation selector
    ("नि", ["नि"]),                                   # a spacing mark (Mc)
])
def test_clusters(text, clusters):
    assert t.clusters(text) == clusters
    assert t.char_count(text) == len(clusters)


def test_a_cut_never_splits_a_character():
    assert t.cut_to_bytes("Zo\u00eb", 3) == "Zo\u00eb"               # a Windows-1252 letter is one byte
    assert t.cut_to_bytes("Zo\u65e5", 3) == "Zo" and t.cut_to_bytes("Zo\u65e5", 4) == "Zo"
    assert t.cut_to_bytes("Zo\u65e5", 5) == "Zo\u65e5"
    assert t.cut_to_bytes("a\U0001f44d\U0001f3fd", 5) == "a"            # 1 + 8 bytes
    assert t.cut_to_bytes("a\U0001f44d\U0001f3fd", 9) == "a\U0001f44d\U0001f3fd"
    field = t.encode_field("\u65e5" * 15, 20)                         # 19 bytes of room: 6 whole letters
    assert len(field) == 20 and field.rstrip(b"\0") == "\u65e5".encode() * 6
    assert t.is_utf8(field.rstrip(b"\0"))
    field = t.encode_field("\u00e9" * 25, 20)                         # one byte each: 19 whole letters
    assert field == b"\xe9" * 19 + b"\0"


# ---- the shared Unicode spec's per-character write rule and per-sequence read rule (the Virtual Villagers Fun
# Patcher's): a Windows-1252 character is its one byte, any other character UTF-8, in the same string; all UTF-8
# only when the mix would read back differently. Each well-formed UTF-8 sequence is its character, every other byte
# is Windows-1252.
@pytest.mark.parametrize("text,data", [
    ("Smith", b"Smith"),
    ("Zo\u00eb", b"Zo\xeb"),                                         # a Windows-1252 letter: its one byte
    ("Zo\u00eb \u65e5\u672c", b"Zo\xeb \xe6\x97\xa5\xe6\x9c\xac"),     # mixed in one string
    ("\u20ac5 \u201cx\u201d", b"\x805 \x93x\x94"),                   # the 0x80..0x9F letters
    ("\u0160ar\u00e1", b"\x8aar\xe1"),
    ("\U0001f600\u00e9", b"\xf0\x9f\x98\x80\xe9"),
    ("x\u0080", b"x\xc2\x80"),                                      # U+0080 has no byte: UTF-8
    ("x\u0081", b"x\x81"),                                           # the five unassigned bytes are the Latin-1 control
])
def test_the_write_rule_is_per_character(text, data):
    assert t.encode(text) == data
    assert t.decode(data) == text


@pytest.mark.parametrize("text", [
    "\u00c3\u00a9",                  # a Windows-1252 "A tilde" then "copyright" would spell the UTF-8 sequence of e acute
    "\u00c3\u00a9\u65e5",           # the same, beside Japanese
    "x\u00e2\u20ac\u00a6",         # "a circumflex, euro, ..." = the UTF-8 sequence of U+2026 when the euro is byte 0x80
    "\u00c2\u00a0",
])
def test_all_utf8_when_the_mix_would_read_back_differently(text):
    data = t.encode(text)
    assert data == text.encode("utf-8")
    assert t.decode(data) == text


def test_a_lead_byte_alone_stays_a_byte():
    assert t.encode("\u00c3") == b"\xc3" and t.encode("\u00c3x") == b"\xc3x"
    assert t.encode("\u00c3\u00e9") == b"\xc3\xe9"       # the second byte is not a continuation


def test_the_read_rule_is_per_sequence_not_per_string():
    assert t.decode(b"Zo\xeb\xe6\x97\xa5") == "Zo\u00eb\u65e5"           # a byte and a sequence in one string
    assert t.decode(b"Caf\xe9 \xc3\xa9") == "Caf\u00e9 \u00e9"
    assert t.decode(b"\xc3") == "\u00c3" and t.decode(b"a\xe6\x97") == "a\u00e6\u2014"
    assert t.decode(b"\xc0\xaf") == "\u00c0\u00af"                       # overlong: two Windows-1252 letters
    assert t.decode(b"\xed\xa0\x80") == "\u00ed\u00a0\u20ac"            # a surrogate: three
    assert t.decode(b"\xf4\x90\x80\x80") == "\u00f4\u0090\u20ac\u20ac"  # past U+10FFFF
    # a hand-typed "A tilde, copyright" in a save written by the old whole-string rule was valid UTF-8 as a whole
    assert t.decode(b"\xc3\x83\xc2\xa9") == "\u00c3\u00a9"
    # and one that is not valid UTF-8 as a whole but holds a valid sequence now reads that sequence
    assert t.decode(b"Zo\xeb\xc3\xa9") == "Zo\u00eb\u00e9"


def test_every_string_round_trips_and_pure_utf8_names_read_as_before():
    import random
    rnd = random.Random(7)
    pool = ["a", "Z", " ", "\u00c3", "\u00a9", "\u00e9", "\u00e2", "\u20ac", "\u0080", "\u0081", "\u201c", "\u0160", "\u65e5",
            "\u0141", "\U0001f600", "\U0001208d", "\u0301", "\u00c2", "\u00a0", "\u2026"]
    for _ in range(3000):
        text = "".join(rnd.choice(pool) for _ in range(rnd.randrange(1, 9)))
        data = t.encode(text)
        assert t.decode(data) == text, text
        assert len(data) <= len(text.encode("utf-8"))                 # never longer than all-UTF-8
        if text.isascii():
            assert data == text.encode()
        # an old UTF-8 name reads as it always did
        assert t.decode(text.encode("utf-8")) == text


def test_the_stored_length_of_a_start_never_shrinks():
    import random
    rnd = random.Random(11)
    pool = ["a", "\u00c3", "\u00a9", "\u00e9", "\u20ac", "\u65e5", "\U0001f600", "\u00c2", "\u00a0"]
    for _ in range(400):
        text = "".join(rnd.choice(pool) for _ in range(rnd.randrange(1, 12)))
        sizes = [len(t.encode(text[:i])) for i in range(len(text) + 1)]
        assert sizes == sorted(sizes), text


def test_log_lines_read_by_the_same_rule():
    data = b"Family: Zo\xc3\xab\r\nOld: Caf\xe9\r\n"
    assert t.decode_lines(data) == "Family: Zoë\r\nOld: Café\r\n"


def test_the_dll_has_the_same_cluster_table():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_vf1_text_tables.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_table_is_this_unicode_version():
    import unicodedata
    if unicodedata.unidata_version != "16.0.0":
        pytest.skip("the table is Unicode 16.0 (Python 3.14)")
    assert t.EXTENDER_RANGES == t.build_extenders()
