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
    assert t.cut_to_bytes("Zoë", 3) == "Zo"
    assert t.cut_to_bytes("Zoë", 4) == "Zoë"
    assert t.cut_to_bytes("a\U0001f44d\U0001f3fd", 5) == "a"            # 1 + 8 bytes
    assert t.cut_to_bytes("a\U0001f44d\U0001f3fd", 9) == "a\U0001f44d\U0001f3fd"
    field = t.encode_field("é" * 15, 20)                         # 19 bytes of room: 9 whole letters
    assert len(field) == 20 and field.rstrip(b"\0") == "é".encode() * 9
    assert t.is_utf8(field.rstrip(b"\0"))


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
