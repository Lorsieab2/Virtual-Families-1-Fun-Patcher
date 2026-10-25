"""Every feature in the patcher window has a "?" with a brief guide (patcher/how_to_use.json).

Same rules as the Virtual Villagers Fun Patcher's tests: every patch and every button, tool and
setting has a guide, no guide is left for something that is gone (so a new patch cannot ship
without one), each guide is short and plain, and the window puts a "?" beside each of them.
"""
import json
import re
import tkinter as tk
from pathlib import Path

import pytest

import vf1_how_to_use as how
import vf1_patcher as vp
import vf1_patcher_gui as gui
from conftest import MANIFEST

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "patcher" / "how_to_use.json").read_text(encoding="utf-8"))
SETTINGS = json.loads(MANIFEST.read_text(encoding="utf-8"))["settings"]

# Every button, tool and setting in the window, by its guide key. A new button gets a guide and a line here.
CONTROLS = {
    "getting_started", "game_folder", "patch_manifest", "output_location", "backup_folder", "load_manifest",
    "defaults", "enable_all", "disable_all", "enable_main", "enable_optional", "dry_run", "enable_disable",
    "restore_backup", "check_for_updates", "back_up_saves", "restore_saves",
    "rename_family", "game_speed", "check_saves", "family_tree",
}

# Words a player never sees in the patcher or the game.
JARGON = re.compile(
    r"\bDLLs?\b|\.dll\b|\b0x[0-9a-f]|\bhooks?\b|trampoline|\boffsets?\b|\bbytes?\b|companion|\bstub\b|"
    r"sidecar|opcode|patch id|\.dat\b|\.json\b|\.ini\b",
    re.IGNORECASE,
)


def all_guides():
    return how.guide_lines()


def test_every_manifest_patch_has_exactly_one_guide():
    guided = [patch_id for entry in DATA["patches"] for patch_id in entry["ids"]]
    assert len(guided) == len(set(guided)), "a patch listed in two guides"
    assert {s["id"] for s in SETTINGS} - set(guided) == set(), "patches without a guide"
    assert set(guided) - {s["id"] for s in SETTINGS} == set(), "guides for patches that are not in the window"


def test_every_control_has_a_guide_and_a_title():
    assert set(DATA["controls"]) == CONTROLS
    for key, entry in DATA["controls"].items():
        assert entry["title"].strip(), key


def test_a_missing_guide_is_refused():
    with pytest.raises(KeyError):
        how.guide(how.patch_key("NoSuchPatch"), "x")
    with pytest.raises(KeyError):
        how.guide("no_such_control")


def test_a_patch_listed_twice_is_an_error(monkeypatch):
    twice = {"patches": [{"ids": ["A"], "guide": ["x"]}, {"ids": ["A"], "guide": ["y"]}], "controls": {}}
    monkeypatch.setattr(how, "_load", lambda: twice)
    how.guide_lines.cache_clear()
    try:
        with pytest.raises(ValueError, match="more than one guide"):
            how.guide_lines()
    finally:
        how.guide_lines.cache_clear()


def test_each_guide_is_brief_and_plain():
    for key, lines in all_guides().items():
        assert 1 <= len(lines) <= how.MAX_LINES, key
        assert sum(len(line) for line in lines) <= how.MAX_GUIDE_CHARS, key
        for line in lines:
            assert line.strip() and line == line.strip(), key
            assert len(line) <= how.MAX_LINE_CHARS, line
            assert JARGON.search(line) is None, line
            assert "**" not in line, line
    for key, lines in all_guides().items():
        if key.startswith("patch:"):
            assert len(lines) >= 3, f"{key}: what it does, how to use it, what to watch out for"


def test_the_experimental_patch_guide_says_so():
    text = " ".join(how.guide(how.patch_key("UpTo28Children"), "x").lines)
    assert "Experimental" in text and "Enable All" in text and "Back Up Saves" in text


def test_the_guides_ship_with_the_patcher():
    source = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    for name in ("vf1_how_to_use.py", "vf1_save_backup.py", "vf1_rename_family.py", "vf1_game_speed.py", "vf1_check_saves.py",
                 "how_to_use.json"):
        assert f'"{name}"' in source


def test_the_gui_wires_every_control_to_a_question_mark():
    source = (ROOT / "patcher" / "vf1_patcher_gui.py").read_text(encoding="utf-8")
    for key in CONTROLS:
        assert re.search(r'"%s"' % re.escape(key), source), key
    body = source[source.index("    def _help_button("):source.index("    def _with_help(")]
    assert 'text="?"' in body and "width=2" in body and "self.help_keys.add(key)" in body
    assert "how_to_use.guide(key, title)" in body       # a key without a guide fails while the window is built


# ------------------------------------------------------------------ the window


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "local_settings_path", lambda base_dir=None: tmp_path / "local.json")
    monkeypatch.setattr(gui, "guess_game_dir", lambda: "")
    top = tk.Toplevel(tk_root)
    top.withdraw()
    window = gui.VF1PatcherGUI(top)
    yield window
    for pending in tk_root.tk.splitlist(tk_root.tk.call("after", "info")):
        tk_root.tk.call("after", "cancel", pending)
    top.destroy()


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def labels(window):
    return [w.cget("text") for w in walk(window) if w.winfo_class() == "TLabel"]


def test_every_control_guide_has_a_question_mark_in_the_window(app):
    assert app.help_keys == CONTROLS


def test_every_patch_row_has_its_own_question_mark(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    app.root.update_idletasks()
    rows = {}
    for box in walk(app.settings_inner):
        if box.winfo_class() == "TCheckbutton":
            rows[box.cget("text")] = [s for s in box.master.winfo_children()
                                     if s.winfo_class() == "TButton" and s.cget("text") == "?"]
    assert set(rows) == {s["label"] for s in SETTINGS}
    assert all(len(buttons) == 1 for buttons in rows.values())
    assert {k for k in app.help_keys if k.startswith("patch:")} == {how.patch_key(s["id"]) for s in SETTINGS}


def test_the_question_mark_opens_the_guide_and_not_twice(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    window = app._show_how_to_use(how.patch_key("FleaMarket"), "Flea Market")
    app.root.update_idletasks()
    assert window.title() == "How to use: Flea Market"
    assert labels(window)[1:] == list(how.guide(how.patch_key("FleaMarket"), "x").lines)
    assert app._show_how_to_use(how.patch_key("FleaMarket"), "Flea Market") is window
    window.destroy()
    again = app._show_how_to_use("back_up_saves")
    assert again.title() == "How to use: Back Up Saves"
    assert labels(again)[0] == "Back Up Saves" and labels(again)[1:] == list(all_guides()["back_up_saves"])


def test_escape_closes_a_guide(app):
    window = app._show_how_to_use("restore_saves")
    app.root.update()
    assert window.bind("<Escape>"), "Escape is bound on the guide window"
    close = next(w for w in walk(window) if w.winfo_class() == "TButton" and w.cget("text") == "Close")
    close.invoke()
    app.root.update()
    assert not window.winfo_exists()


def test_clicking_the_question_mark_button_opens_its_guide(app):
    buttons = [w for w in walk(app.root) if w.winfo_class() == "TButton" and w.cget("text") == "?"]
    assert len(buttons) >= len(CONTROLS) - 1
    buttons[0].invoke()
    assert any(w.winfo_exists() for w in app._help_windows.values())
