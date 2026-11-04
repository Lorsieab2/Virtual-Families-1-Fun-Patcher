"""Unicode 18.0 (the owner, 2026-11-03: "yeah you can add them! to all the games!", "as long as the unicode LOOKS similar
to the in-game fonts").

* The bundled files: the Unicode 18.0.0 tables (patcher/vf1_unicode18.py, from the Unicode Character Database; their
  sources' SHA-256s are the ones scripts/fetch_unicode18.py checks, and the Unicode licence ships) and the open fonts
  (patcher/payload/UnicodeFonts: GNU Unifont 18.0.01, Noto Sans Cuneiform, Noto Serif Tangut, Last Resort 18.000, each
  with its licence and SOURCES.json entry, byte for byte), installed with both Unicode settings.
* The tables are used: the cluster rule's marks and the colour emoji list are 18.0's (newer than Python's and
  Windows'), and every emoji Windows' ICU knows is in the list.
* Coverage: EVERY assigned Unicode 18.0 code point (controls and surrogates aside) gets a glyph from the chain, the
  shipped fonts last.
* The REAL vf1text.dll / vf1font.dll on the REAL exe in Unicorn, real GDI: a letter only a shipped font has is drawn
  from it, the font loaded privately from memory by the DLL (AddFontMemResourceEx) only when the chain first needs it,
  in the game font's height, baseline, weight and coverage curve, pixel for pixel as the patcher's tools draw it;
  ordinary text never opens the files."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unicodedata

import pytest

from conftest import ROOT

import vf1_emoji
import vf1_text
import vf1_unicode18 as u18

sys.path.insert(0, str(ROOT / "scripts"))
import fetch_unicode18 as fetch  # noqa: E402

FONTS = ROOT / "patcher" / "payload" / "UnicodeFonts"
FONT_FILES = ("unifont-18.0.01.otf", "unifont_upper-18.0.01.otf", "NotoSansCuneiform-Regular.otf",
              "NotoSerifTangut-Regular.otf", "LastResortHE-Regular.ttf")
LICENCES = ("Unifont-OFL-1.1.txt", "Unifont-GPL-2.0-COPYING.txt", "NotoSansCuneiform-OFL-1.1.txt",
            "NotoSerifTangut-OFL-1.1.txt", "LastResort-OFL-1.1.txt")


def new_since_python(limit_per_block: int = 2) -> list[int]:
    """Code points assigned in Unicode 18.0 that this Python's unicodedata (16.0) does not know, a few per block."""
    out, seen = [], {}
    for a, b in u18.ASSIGNED:
        for cp in range(a, b + 1):
            if unicodedata.category(chr(cp)) == "Cn" and not (0xE000 <= cp <= 0xF8FF or cp >= 0xF0000):
                block = cp >> 7
                if seen.get(block, 0) < limit_per_block:
                    seen[block] = seen.get(block, 0) + 1
                    out.append(cp)
    return out


# --------------------------------------------------------------------------- the files
def test_the_fonts_and_licences_are_the_verified_files():
    record = json.loads((FONTS / "SOURCES.json").read_text(encoding="utf-8"))["files"]
    for name in FONT_FILES + LICENCES:
        data = (FONTS / name).read_bytes()
        assert record[name]["sha256"] == hashlib.sha256(data).hexdigest().upper(), name
        assert record[name]["bytes"] == len(data), name
        if name in fetch.EXPECTED:
            assert fetch.EXPECTED[name] == record[name]["sha256"], name
    assert "OpenPGP signature" in record["unifont-18.0.01.otf"]["verified"]
    assert "published" in record["LastResortHE-Regular.ttf"]["verified"]
    assert sorted(p.name for p in FONTS.iterdir()) == sorted(FONT_FILES + LICENCES + ("SOURCES.json",))


def test_the_tables_come_from_the_checked_ucd_files():
    for name, sha in u18.SOURCES.items():
        assert fetch.EXPECTED[name] == sha, name
    licence = (ROOT / "data" / "unicode18" / "LICENSE-Unicode.txt").read_bytes()
    assert hashlib.sha256(licence).hexdigest().upper() == fetch.EXPECTED["license.txt"]
    ucd = os.environ.get("VF1_UCD18_DIR")
    if ucd:                                                # rebuilt from the downloaded files: the same module
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_vf1_unicode18.py"), "--ucd", ucd, "--check"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_both_unicode_settings_install_the_fonts():
    manifest = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in manifest["settings"]}
    for pid, sub in (("RenderUnicodeInGameFonts", "Unicode Text"), ("UseUnicodeFont", "Unicode Font")):
        files = {f["source"]: f["target"] for f in by_id[pid]["files"]}
        for name in FONT_FILES + LICENCES:
            assert files[f"UnicodeFonts/{name}"] == f"Virtual Families 1 Patcher Files/{sub}/Fonts/{name}", (pid, name)


def test_the_credits_name_the_fonts_and_the_ucd():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for who in ("GNU Unifont", "Noto Sans Cuneiform", "Noto Serif Tangut", "Last Resort", "Unicode Character Database"):
        assert who in readme, who


# --------------------------------------------------------------------------- the tables are used
def test_the_cluster_marks_and_the_emoji_list_are_unicode_18():
    marks = {cp for a, b in u18.EXTENDER_MARKS for cp in range(a, b + 1)}
    newer = [cp for cp in marks if unicodedata.category(chr(cp)) == "Cn"]
    assert newer, "18.0 has marks this Python does not know"
    for cp in newer:
        assert vf1_text.is_cluster_extender(cp)
        assert len(vf1_text.clusters("a" + chr(cp))) == 1
    assert vf1_emoji.EMOJI_PRESENTATION_RANGES is u18.EMOJI_PRESENTATION
    inc = (ROOT / "native" / "vf1text" / "extenders.inc").read_text(encoding="utf-8")
    assert vf1_text.cluster_table_c() == inc.replace("\r\n", "\n")


def test_every_emoji_windows_knows_is_in_the_list():
    icu = pytest.importorskip("ctypes")
    try:
        old = vf1_emoji.build_emoji_presentation()
    except OSError:
        pytest.skip("needs Windows' icu.dll")
    ours = {cp for a, b in u18.EMOJI_PRESENTATION for cp in range(a, b + 1)}
    assert {cp for a, b in old for cp in range(a, b + 1)} <= ours
    assert icu


# --------------------------------------------------------------------------- coverage
def test_every_assigned_unicode_18_code_point_gets_a_glyph():
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    r = g.Renderer("Segoe UI", 700, 16, 13, 18)
    never = {cp for a, b in u18.NOT_DRAWN for cp in range(a, b + 1)}
    missing = [cp for a, b in u18.ASSIGNED for cp in range(a, b + 1)
               if cp not in never and r.face_for(chr(cp)) is None]
    assert missing == [], [hex(cp) for cp in missing[:20]]
    assert sum(b - a + 1 for a, b in u18.ASSIGNED) > 300000


# --------------------------------------------------------------------------- the real DLLs
def _build(tmp_path_factory):
    vcvars = r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat"
    if os.name != "nt" or not os.path.isfile(vcvars):
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("u18_build")
    installer = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                             "Microsoft Visual Studio", "Installer")
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}", VF1_BUILD_DIR=str(out))
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return _build(tmp_path_factory)


def _world(built, vanilla_dir, name):
    pytest.importorskip("unicorn")
    import text_emu
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", built / name, vanilla_dir, install=True,
                           real_gdi=True)
    assert w.installed == 1
    return w


@pytest.mark.parametrize("dll_name", ["vf1text.dll", "vf1font.dll"])
def test_the_dll_loads_the_shipped_fonts_only_when_needed_and_draws_from_them(built, vanilla_dir, dll_name):
    import vf1_game_fonts as gf
    import vf1_picture_image as pi
    w = _world(built, vanilla_dir, dll_name)
    w.draw(vf1_text.encode("Zo\u00eb \u65e5\u672c \u0645\u0631\u062d\u0628\u0627 \U0001F600"), "SegoeUiBold18")
    assert w.font_opens == [] and w.loaded_font_bytes == []                  # ordinary text: the files stay shut
    samples = [0x17000, 0x18B00, 0x12480, 0xE000] + new_since_python(1)[:24]   # Tangut, Khitan, cuneiform, PUA, new
    fonts = gf.Fonts(vanilla_dir)
    for font in ("SegoeUiBold18", "SegoeUiBold24"):
        f = fonts.font(font) if dll_name == "vf1text.dll" else None
        for cp in samples:
            text = chr(cp)
            blits = w.draw(vf1_text.encode(text), font, x=2, y=3)
            assert len(blits) == 1, hex(cp)
            if f is not None:
                glyph = f.glyph(text)
                assert glyph.kind == "drawn by Windows" and glyph.face, (hex(cp), glyph.kind)
                kind, surface, box, place = blits[0][:4]
                info = w.surfaces[surface]
                piece = pi.Image(info["w"], info["h"], w.surface_pixels(surface)).sub(*box)
                assert box[2] == glyph.width and bytes(piece.data[3::4]) == bytes(glyph.image.data[3::4]), hex(cp)
    assert sorted(set(w.font_opens)) == sorted(FONT_FILES)                     # each file opened once
    assert len(w.font_opens) == len(FONT_FILES)
    assert sum(w.loaded_font_bytes) == sum((FONTS / n).stat().st_size for n in FONT_FILES)


def test_unifont_letters_are_thickened_in_the_bold_fonts_only():
    """The owner, 2026-11-03: Unifont letters bolder -- a one-pixel synthetic-bold offset in the bold game fonts; the
    regular SegoeUi33 keeps the smooth scaled letter."""
    import vf1_glyph_gdi as g
    if not g.AVAILABLE:
        pytest.skip("needs Windows GDI")
    letter = next(chr(cp) for cp in new_since_python(1)
                  if g.Renderer("Segoe UI", 700, 16, 13, 18).face_for(chr(cp)) == "Unifont Upper")
    bold, face = g.Renderer("Segoe UI", 700, 16, 13, 18).draw(letter)
    plain, _ = g.Renderer("Segoe UI", 400, 16, 13, 18).draw(letter)
    assert face == "Unifont Upper" and bold.width == plain.width + 1
    assert sum(bold.data[3::4]) > sum(plain.data[3::4])
    a, _ = g.Renderer("Segoe UI", 400, 31, 26, 33).draw(letter)
    b, _ = g.Renderer("Segoe UI", 400, 31, 26, 33).draw(letter)
    assert a == b                                         # regular: no offset
    latin, _ = g.Renderer("Segoe UI", 700, 16, 13, 18).draw("\u0141")
    assert latin.width == g.Renderer("Segoe UI", 700, 16, 13, 18, ()).draw("\u0141")[0].width
