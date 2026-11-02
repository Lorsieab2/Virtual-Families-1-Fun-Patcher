"""Use Unicode Font (overrides in-game fonts): the setting, its exclusion with Render Unicode with In-Game Fonts (the
manifest, the command line, the patcher window and Patch Selection Settings), the Unicode Font tool, and vf1font.dll
drawing the game's text with the chosen font (the real DLL on the real exe in Unicorn, real GDI)."""
import argparse
import json
import os
import tkinter as tk
from pathlib import Path

import pytest

from conftest import MANIFEST, ROOT

import vf1_game_fonts as gf
import vf1_glyph_gdi as gdi
import vf1_patcher as vp
import vf1_text
import vf1_unicode_font as uf

ARIAL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts" / "arial.ttf"


def settings():
    return vp.manifest_settings(json.loads(MANIFEST.read_text(encoding="utf-8")))


def ns(**kw):
    base = dict(enable=None, disable=None, enable_all=False, disable_all=False)
    base.update(kw)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- the setting
def test_the_setting_and_its_exclusion():
    s = settings()
    row = s["UseUnicodeFont"]
    assert row.label == "Use Unicode Font (overrides in-game fonts)" and row.default is False
    assert row.excludes == ("RenderUnicodeInGameFonts",) and s["RenderUnicodeInGameFonts"].excludes == ("UseUnicodeFont",)
    assert s["RenderUnicodeInGameFonts"].label == "Render Unicode with In-Game Fonts" and s["RenderUnicodeInGameFonts"].default
    assert {f.target for f in row.files} == {
        "Virtual Families 1 Patcher Files/vf1font.dll",
        *(f"Virtual Families 1 Patcher Files/Unicode Font/{n}.txt" for n in gf.GAME_FONTS)}
    assert "Cannot be on with Render Unicode with In-Game Fonts" in vp.excludes_note(row, s)


def test_the_command_line_picks_one_and_refuses_both():
    s = settings()
    defaults = vp.resolve_enabled_settings(s, ns())
    assert "RenderUnicodeInGameFonts" in defaults and "UseUnicodeFont" not in defaults
    chosen = vp.resolve_enabled_settings(s, ns(enable=["UseUnicodeFont"]))
    assert "UseUnicodeFont" in chosen and "RenderUnicodeInGameFonts" not in chosen
    every = vp.resolve_enabled_settings(s, ns(enable_all=True))
    assert "RenderUnicodeInGameFonts" in every and "UseUnicodeFont" not in every
    every = vp.resolve_enabled_settings(s, ns(enable_all=True, enable=["UseUnicodeFont"]))
    assert "UseUnicodeFont" in every and "RenderUnicodeInGameFonts" not in every
    with pytest.raises(vp.PatchError, match="cannot both be on"):
        vp.resolve_enabled_settings(s, ns(enable=["UseUnicodeFont", "RenderUnicodeInGameFonts"]))
    off = vp.resolve_enabled_settings(s, ns(disable=["RenderUnicodeInGameFonts"]))
    assert not {"RenderUnicodeInGameFonts", "UseUnicodeFont"} & off


def test_the_manifest_refuses_bad_exclusions():
    def manifest(rows):
        return {"settings": rows}
    with pytest.raises(vp.PatchError, match="unknown"):
        vp.manifest_settings(manifest([{"id": "A", "excludes": ["B"]}]))
    with pytest.raises(vp.PatchError, match="itself"):
        vp.manifest_settings(manifest([{"id": "A", "excludes": ["A"]}]))
    with pytest.raises(vp.PatchError, match="both be on by default"):
        vp.manifest_settings(manifest([{"id": "A", "default": True, "excludes": ["B"]}, {"id": "B", "default": True}]))
    s = vp.manifest_settings(manifest([{"id": "A", "excludes": ["B"]}, {"id": "B"}]))
    assert s["B"].excludes == ("A",)                       # always both ways


# --------------------------------------------------------------------------- the patcher window
from test_gui import app, tk_root  # noqa: E402,F401  (the patcher window, as tests/test_gui.py makes it)


def test_ticking_one_unticks_the_other(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    app.select_default_settings()
    assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()
    app.setting_vars["UseUnicodeFont"].set(True)
    assert not app.setting_vars["RenderUnicodeInGameFonts"].get()
    app.setting_vars["RenderUnicodeInGameFonts"].set(True)
    assert not app.setting_vars["UseUnicodeFont"].get()
    app.select_owners_defaults()       # the owner (2026-11-01): Render Unicode with In-Game Fonts, not Use Unicode Font
    assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()
    app.setting_vars["UseUnicodeFont"].set(True)
    app.select_owners_defaults()
    assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()
    app.select_all_settings()
    assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()
    app.clear_all_settings()
    app.select_category_settings("main")
    assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()


def test_patch_selection_settings_refuses_both(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    app.select_default_settings()
    dialog = app.open_patch_selection_settings()
    try:
        app.quiet_selection = True
        choices = {sid: var for sid, _l, var, _b in app._patch_selection_choices}
        choices["UseUnicodeFont"].set(True)
        choices["RenderUnicodeInGameFonts"].set(True)
        app._patch_selection_apply(True)
        assert "cannot both be on" in app.last_selection_problem
        assert app.setting_vars["RenderUnicodeInGameFonts"].get() and not app.setting_vars["UseUnicodeFont"].get()
        choices["RenderUnicodeInGameFonts"].set(False)
        app._patch_selection_apply(True)
        assert app.setting_vars["UseUnicodeFont"].get() and not app.setting_vars["RenderUnicodeInGameFonts"].get()
    finally:
        dialog.destroy()


# --------------------------------------------------------------------------- the Unicode Font tool
def test_the_choice_is_written_beside_the_other_settings(tmp_path):
    ini = tmp_path / vp.PATCHER_FOLDER / vp.SETTINGS_INI
    with pytest.raises(uf.FontChoiceError, match="patched"):
        uf.write_choice(tmp_path, "Arial")
    ini.parent.mkdir(parents=True)
    ini.write_bytes(b"[Patches]\r\nUseUnicodeFont=1\r\n\r\n[Cheats]\r\nInterestRate=9\r\n")
    assert uf.read_choice(tmp_path) == ("Segoe UI", "")
    uf.write_choice(tmp_path, "Comic Sans MS")
    assert uf.read_choice(tmp_path) == ("Comic Sans MS", "") and uf.is_on(tmp_path)
    uf.write_choice(tmp_path, "Arial")
    data = ini.read_bytes()
    assert data.count(b"[UnicodeFont]") == 1 and b"InterestRate=9" in data and b"UseUnicodeFont=1" in data
    assert vp.read_ini_section(data, "UnicodeFont") == {"Face": "Arial", "File": ""}
    with pytest.raises(uf.FontChoiceError):
        uf.write_choice(tmp_path, "\u5fae\u8f6f\u96c5\u9ed1")


def test_a_font_file_is_copied_and_named(tmp_path):
    if not ARIAL.is_file():
        pytest.skip("needs Windows' Arial")
    assert gdi.font_file_family(ARIAL.read_bytes()) == "Arial"
    assert gdi.font_file_family(b"not a font") is None
    ini = tmp_path / vp.PATCHER_FOLDER / vp.SETTINGS_INI
    ini.parent.mkdir(parents=True)
    ini.write_bytes(b"[Patches]\r\nUseUnicodeFont=1\r\n")
    uf.write_choice(tmp_path, "ignored", ARIAL)
    assert uf.read_choice(tmp_path) == ("Arial", "arial.ttf")
    assert (tmp_path / vp.PATCHER_FOLDER / uf.FONT_FOLDER / "arial.ttf").read_bytes() == ARIAL.read_bytes()
    with pytest.raises(uf.FontChoiceError):
        uf.write_choice(tmp_path, "x", tmp_path / vp.PATCHER_FOLDER / vp.SETTINGS_INI)


def test_the_size_is_fitted_to_the_games_width(vanilla_dir):
    if not gdi.AVAILABLE:
        pytest.skip("needs Windows")
    fonts = gf.Fonts(vanilla_dir)
    for name in gf.GAME_FONTS:
        f = fonts.font(name)
        game = f.width(gf.FIT_REFERENCE)
        for face in ("Segoe UI", "Arial", "Comic Sans MS", "Courier New"):
            o = f.with_unicode_font(face)
            em = o.override[1]
            assert f.style.em * 6 // 10 <= em <= f.style.em * 13 // 10
            if f.style.em * 6 // 10 < em < f.style.em * 13 // 10:
                drawn = o.renderer().extent(gf.FIT_REFERENCE)
                # within about 7% (one step of a fixed-width font's size moves a whole line by ~5%)
                assert abs(drawn - game) <= max(8, game // 15), (name, face, drawn, game)
            assert all(o.glyph(c).kind != "game" for c in "Hello")
        assert f.with_unicode_font("No Such Font Anywhere").override[1] == f.style.em


# --------------------------------------------------------------------------- vf1font.dll in the game
@pytest.fixture(scope="module")
def dlls(tmp_path_factory):
    from test_vf1_unicode_text import VCVARS, build_env
    import subprocess
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    out = tmp_path_factory.mktemp("font_build")
    r = subprocess.run(["cmd.exe", "/c", str(ROOT / "native" / "build_text.bat")], capture_output=True, text=True,
                       env=dict(build_env(), VF1_BUILD_DIR=str(out)))
    assert r.returncode == 0, r.stdout + r.stderr
    return out


@pytest.mark.parametrize("face,file", [("Segoe UI", None), ("Comic Sans MS", None), ("Arial", "arial.ttf")])
def test_vf1font_draws_every_letter_with_the_chosen_font(dlls, vanilla_dir, face, file):
    """The game's DrawString and GetWidth with vf1font.dll: the game's own letters too are drawn by the chosen font,
    each place, box and pixel as the patcher's preview (vf1_game_fonts with_unicode_font) draws them."""
    if not gdi.AVAILABLE:
        pytest.skip("needs Windows")
    if file and not ARIAL.is_file():
        pytest.skip("needs Windows' Arial")
    import text_emu
    import vf1_picture_image as pi
    ini = {("UnicodeFont", "Face"): face}
    if file:
        ini[("UnicodeFont", "File")] = file
    w = text_emu.TextWorld(vanilla_dir / "Virtual Families.exe", dlls / "vf1font.dll", vanilla_dir, install=True,
                           real_gdi=True, ini=ini)
    if file:
        w.font_files[text_emu.FONT_FOLDER + file] = ARIAL
    assert w.installed == 1
    fonts = gf.Fonts(vanilla_dir)
    for font in gf.GAME_FONTS:
        f = fonts.font(font).with_unicode_font(face)
        for text in ["The Smith Family", "Zo\u00eb \u0130lkay \u65e5\u672c", "Line 1\nLine 2!"]:
            data = vf1_text.encode(text)
            blits = w.draw(data, font, x=1, y=2)
            ours = f.layout(text, 1, 2)
            assert len(blits) == len(ours), (font, text)
            for (kind, surface, box, place), (glyph, x, y) in zip(blits, ours):
                assert place == (x, y) and box[2] == glyph.width, (font, text)
                assert glyph.kind != "game"
                info = w.surfaces[surface]
                piece = pi.Image(info["w"], info["h"], w.surface_pixels(surface)).sub(*box)
                assert bytes(piece.data[3::4]) == bytes(glyph.image.data[3::4]), (font, text)
            assert w.width(data, font) == f.width(text)
    if file:
        assert "AddFontResourceExW" in w.gdi_calls


def test_the_unicode_font_window(app, vanilla_dir, tmp_path):
    folder = tmp_path / "modded"
    (folder / vp.PATCHER_FOLDER).mkdir(parents=True)
    for name in ("Virtual Families.exe",):
        (folder / name).write_bytes((vanilla_dir / name).read_bytes())
    (folder / "Images").mkdir()
    for name in gf.GAME_FONTS:
        (folder / "Images" / f"{name}.png").write_bytes((vanilla_dir / "Images" / f"{name}.png").read_bytes())
    (folder / vp.PATCHER_FOLDER / vp.SETTINGS_INI).write_bytes(b"[Patches]\r\nUseUnicodeFont=1\r\n")
    window = uf.open_window(app.root, game_folders=[folder])
    try:
        window.quiet = True
        assert "Use Unicode Font is on" in window.status_var.get() and window.face == "Segoe UI"
        assert len(window._photos) == 4
        assert "Arial" in window.faces
        window.set_face("Arial")
        assert window.save() is not None
        assert uf.read_choice(folder) == ("Arial", "")
    finally:
        window.close()


def test_the_game_text_tool_previews_use_unicode_font(app, vanilla_dir):
    import vf1_game_text as tool
    window = tool.open_window(app.root, game_folders=[vanilla_dir])
    try:
        window.quiet = True
        window.unicode_var.set(True)
        window.unicode_face_var.set("Arial")
        font = window.current_font()
        assert font.override is not None and font.override[0] == "Arial"
        window.refresh()
        assert "drawn by Windows" in window.info_var.get()
    finally:
        window.close()
