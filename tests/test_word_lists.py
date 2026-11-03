"""The shared ICU 77-1 word lists (patcher/payload/WordLists, copied unchanged from unicode-audit/word-lists): the
fallback for Thai, Lao, Khmer, Burmese, Chinese and Japanese line breaking when Windows has no icu.dll
(native/vf1text/wordlists.inc, patcher/vf1_line_break.py `dictionary_inside`).

* Every file is byte for byte the shared copy (SHA-256), and the licence ships with the lists.
* The patcher's segmentation: longest match, no break inside a word, lists read only when needed.
* The REAL vf1text.dll / vf1font.dll on the REAL exe in Unicorn, with icu.dll missing: the game's word wrapper lays out
  text in every one of these scripts exactly as vf1_line_break.wrap(use_icu=False) does, never inside a list word;
  English text never opens a list; with icu.dll, no list is ever opened."""
import hashlib
import json

import pytest

from conftest import ROOT

import vf1_line_break as lb
import vf1_text

LISTS = ROOT / "patcher" / "payload" / "WordLists"
README_SHA256 = "074575a4a301b7d1ff2c149ae249d2c6b6a5bef059d1be46f1c51caf66353ab2"   # unicode-audit's README.md

SENTENCES = {
    "thaidict.txt": "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e04\u0e23\u0e31\u0e1a\u0e1c\u0e21\u0e0a\u0e37\u0e48\u0e2d"
                    "\u0e2a\u0e21\u0e0a\u0e32\u0e22\u0e04\u0e23\u0e2d\u0e1a\u0e04\u0e23\u0e31\u0e27\u0e02\u0e2d\u0e07"
                    "\u0e40\u0e23\u0e32\u0e21\u0e35\u0e40\u0e14\u0e47\u0e01\u0e2b\u0e25\u0e32\u0e22\u0e04\u0e19",
    "laodict.txt": "\u0eaa\u0eb0\u0e9a\u0eb2\u0e8d\u0e94\u0eb5\u0e84\u0ead\u0e9a\u0e84\u0ebb\u0ea7\u0e82\u0ead\u0e87"
                   "\u0e9e\u0ea7\u0e81\u0ec0\u0eae\u0ebb\u0eb2\u0ea1\u0eb5\u0ec0\u0e94\u0eb1\u0e81\u0eab\u0ebc\u0eb2"
                   "\u0e8d\u0e84\u0ebb\u0e99",
    "khmerdict.txt": "\u179f\u17bd\u179f\u17d2\u178f\u17b8\u1782\u17d2\u179a\u17bd\u179f\u17b6\u179a\u1799\u17be"
                     "\u1784\u1798\u17b6\u1793\u1780\u17bc\u1793\u1785\u17d2\u179a\u17be\u1793",
    "burmesedict.txt": "\u1019\u1004\u103a\u1039\u1002\u101c\u102c\u1015\u102b\u1000\u103b\u103d\u1014\u103a"
                       "\u102f\u1015\u103a\u1010\u102d\u102f\u1037\u1019\u102d\u101e\u102c\u1038\u1005\u102f"
                       "\u1019\u103e\u102c\u1000\u101c\u1031\u1038\u1019\u103b\u102c\u1038\u101b\u103e\u102d"
                       "\u1010\u101a\u103a",
    "cjdict.txt": "\u6211\u4eec\u7684\u5bb6\u5ead\u5f88\u5927\uff0c\u6709\u5f88\u591a\u5b69\u5b50\u3002\u65e5\u672c"
                  "\u8a9e\u306e\u6587\u7ae0\u3067\u3059\u3002\u5b50\u4f9b\u305f\u3061\u306f\u5ead\u3067\u904a"
                  "\u3093\u3067\u3044\u307e\u3059\u3002",
}


def _readme_table() -> dict[str, str]:
    text = (LISTS / "README.md").read_text(encoding="utf-8")
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 5 and cells[1].startswith("`") and cells[4].startswith("`"):
            out[cells[1].strip("`")] = cells[4].strip("`")
    return out


# --------------------------------------------------------------------------- the files
def test_every_file_is_the_shared_copy_byte_for_byte():
    table = _readme_table()
    assert set(table) == set(lb.WORD_LIST_FILES) | {"ICU-LICENSE.txt"}
    assert table == lb.WORD_LIST_SHA256
    for name, sha in table.items():
        assert hashlib.sha256((LISTS / name).read_bytes()).hexdigest() == sha, name
    assert hashlib.sha256((LISTS / "README.md").read_bytes()).hexdigest() == README_SHA256
    assert sorted(p.name for p in LISTS.iterdir()) == sorted(list(table) + ["README.md"])


def test_the_lists_and_licence_are_installed_with_both_unicode_settings():
    manifest = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in manifest["settings"]}
    for pid, sub in (("RenderUnicodeInGameFonts", "Unicode Text"), ("UseUnicodeFont", "Unicode Font")):
        files = {f["source"]: f["target"] for f in by_id[pid]["files"]}
        for name in list(lb.WORD_LIST_FILES) + ["ICU-LICENSE.txt"]:
            assert files[f"WordLists/{name}"] == f"Virtual Families 1 Patcher Files/{sub}/Word Lists/{name}", (pid, name)


def test_the_readme_credits_the_lists():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for who in ("ICU", "Lao", "Myanmar Karen", "Libtabe", "IPADIC", "ICU-LICENSE.txt"):
        assert who in readme, who


# --------------------------------------------------------------------------- the patcher's rule
def test_segmentation_is_longest_match_and_never_breaks_inside_a_word():
    text = SENTENCES["thaidict.txt"][:12]          # สวัสดี ครับ ผม
    assert lb.dictionary_inside(text) == set(range(1, 6)) | set(range(7, 10)) | {11}
    breaks, _ = lb.break_points(text, use_icu=False)
    assert breaks == {6, 10}                       # the same as ICU's (test_line_break)
    for name, sentence in SENTENCES.items():
        breaks, any_letter = lb.break_points(sentence, use_icu=False)
        inside = lb.dictionary_inside(sentence)
        assert any_letter and breaks and inside, name
        assert not breaks & inside, name


def test_a_missing_list_leaves_the_built_in_breaks(monkeypatch, tmp_path):
    monkeypatch.setattr(lb, "word_list_dir", tmp_path)
    monkeypatch.setattr(lb, "_word_lists", {})
    text = SENTENCES["thaidict.txt"][:12]
    assert lb.dictionary_inside(text) == set()
    assert len(lb.break_points(text, use_icu=False)[0]) > 2


def test_lists_are_read_only_when_needed(monkeypatch):
    read = []
    real = lb.parse_word_list
    monkeypatch.setattr(lb, "_word_lists", {})
    monkeypatch.setattr(lb, "parse_word_list", lambda data: read.append(len(data)) or real(data))
    lb.break_points("Hello there, a plain English sentence.", use_icu=False)
    lb.break_points("Korean \ud55c\uad6d\uc5b4 \ubb38\uc7a5", use_icu=False)
    assert read == []
    lb.break_points(SENTENCES["thaidict.txt"], use_icu=False)
    assert read == [(LISTS / "thaidict.txt").stat().st_size]


# --------------------------------------------------------------------------- the real DLLs, without icu.dll
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import os
    import subprocess
    vcvars = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
    if os.name != "nt" or not os.path.isfile(vcvars):
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("words_build")
    installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             "Microsoft Visual Studio", "Installer")
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}", VF1_BUILD_DIR=str(out))
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(scope="module")
def fonts(vanilla_dir):
    import vf1_game_fonts as gf
    return gf.Fonts(vanilla_dir)


@pytest.fixture(scope="module")
def ratio(vanilla_dir):
    return lb.justify_ratio((vanilla_dir / "Virtual Families.exe").read_bytes())


def _world(built, vanilla_dir, name, icu):
    pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    import text_emu
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", built / name, vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    w.icu = icu and w.icu
    return w


def _blits(blits):
    return [(b[3], b[2][2]) for b in blits]


def _model(font, draws):
    return [((gx, gy), g.width) for text, x, y in draws for g, gx, gy in font.layout(text, x, y)]


@pytest.mark.parametrize("dll_name", ["vf1text.dll", "vf1font.dll"])
def test_without_icu_the_dll_breaks_only_between_list_words(built, vanilla_dir, fonts, ratio, dll_name):
    w = _world(built, vanilla_dir, dll_name, icu=False)
    f = fonts.font("SegoeUiBold18")
    for name, sentence in SENTENCES.items():
        for width in (160, 90):
            data = vf1_text.encode(sentence)
            got, blits = w.wrap(data, width, limit=200_000_000)
            want, draws = lb.wrap(f, sentence, 0, 0, width, ratio, use_icu=False)
            if dll_name == "vf1text.dll":
                assert got == want and _blits(blits) == _model(f, draws), (name, width)
            # the pieces the DLL drew start only at allowed breaks: never inside a list word
            assert len({y for (x, y), _ in _blits(blits)}) > 1, (name, width)
        assert w.word_list_opens.count(name) == 1, name           # read once, then kept
    assert w.icu_calls == []


def test_without_icu_english_never_opens_a_list(built, vanilla_dir):
    w = _world(built, vanilla_dir, "vf1text.dll", icu=False)
    w.wrap(b"Your family has grown! A new baby has arrived, and everyone is happy.", 160, limit=50_000_000)
    w.wrap(vf1_text.encode("Korean \ud55c\uad6d\uc5b4 \ubb38\uc7a5\uc785\ub2c8\ub2e4."), 60, limit=50_000_000)
    assert w.word_list_opens == []


def test_with_icu_no_list_is_ever_opened(built, vanilla_dir):
    if lb.icu() is None:
        pytest.skip("needs icu.dll")
    w = _world(built, vanilla_dir, "vf1text.dll", icu=True)
    for sentence in SENTENCES.values():
        w.wrap(vf1_text.encode(sentence), 90, limit=200_000_000)
    assert w.word_list_opens == []


def test_without_icu_a_missing_list_keeps_the_built_in_breaks(built, vanilla_dir, fonts, ratio, tmp_path,
                                                              monkeypatch):
    w = _world(built, vanilla_dir, "vf1text.dll", icu=False)
    w.word_lists = tmp_path                               # an empty folder: no list can be read
    monkeypatch.setattr(lb, "word_list_dir", tmp_path)
    monkeypatch.setattr(lb, "_word_lists", {})
    f = fonts.font("SegoeUiBold18")
    sentence = SENTENCES["thaidict.txt"]
    got, blits = w.wrap(vf1_text.encode(sentence), 90, limit=200_000_000)
    want, draws = lb.wrap(f, sentence, 0, 0, 90, ratio, use_icu=False)
    assert got == want and _blits(blits) == _model(f, draws)
