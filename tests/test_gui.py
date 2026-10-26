"""The ported window (vf1_patcher_gui.py)."""
import json
import time
import tkinter as tk
from pathlib import Path

import pytest

import vf1_patcher as vp
import vf1_patcher_gui as gui
from conftest import MANIFEST, write_manifest


def test_bold_markup_and_description_line():
    assert gui.markup_segments("a **b** c") == [("a ", False), ("b", True), (" c", False)]
    settings = vp.manifest_settings({"settings": [
        {"id": "Base", "label": "Base", "default": True, "description": "Base thing."},
        {"id": "Top", "label": "Top", "description": "Needs base.", "requires": ["Base"]},
    ]})
    pre = gui.setting_closure_maps(settings)
    assert gui.setting_description_text(settings["Top"], settings, pre["Top"]) == \
        "Top - default off - Needs base. **Requires: Base.**"
    assert gui.setting_description_text(settings["Base"], settings, pre["Base"]) == "Base - default on - Base thing."


def test_apply_namespace_selects_exactly_the_ticked_settings():
    settings = vp.manifest_settings(json.loads(MANIFEST.read_text(encoding="utf-8")))
    args = gui.build_apply_namespace(game_dir='"C:/Games/VF"', manifest=str(MANIFEST), output_dir="",
                                     settings=settings, selected_settings={"FleaMarket"})
    assert args.game_dir == "C:/Games/VF" and args.output_dir is None
    assert vp.resolve_enabled_settings(settings, args) == {"FleaMarket"}
    with pytest.raises(vp.PatchError, match="Choose your vanilla"):
        gui.build_apply_namespace(game_dir="", manifest=str(MANIFEST), settings=settings)
    with pytest.raises(vp.PatchError, match="Unknown"):
        gui.build_apply_namespace(game_dir="x", manifest=str(MANIFEST), settings=settings, selected_settings={"Nope"})


def test_saved_paths_round_trip(tmp_path):
    path = tmp_path / "local.json"
    gui.save_saved_paths(vanilla_game_dir=" C:/VF ", modded_output_dir="D:/Out", settings_path=path)
    gui.save_saved_paths(modded_output_parent_dir="D:/", settings_path=path)
    assert gui.load_saved_paths(path) == {"vanilla_game_dir": "C:/VF", "modded_output_dir": "D:/Out",
                                          "modded_output_parent_dir": "D:/"}
    path.write_text("not json")
    assert gui.load_saved_paths(path) == {}


def test_modified_file_log_lines():
    lines = gui.success_file_lines({"written_files": [{"file_path": "a.ini", "action": "replaced"}],
                                    "removed_files": ["b.png"], "unchanged_files": ["c.dll"],
                                    "vanilla_files_copied": 3})
    assert lines == ["- a.ini (replaced)", "- b.png (removed)", "- c.dll (already up to date)",
                     "- 3 unchanged game file(s) copied from the vanilla folder"]
    assert gui.success_file_lines({}) == ["(none)"]


@pytest.fixture(scope="module")
def tk_root():
    # One interpreter for the module: creating and destroying several tk.Tk()
    # in one process makes Tcl intermittently fail to find init.tcl.
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
    window._open_work_wait = lambda label: None  # no popup during tests
    yield window
    # The window queues an after_idle(lambda) for every markup label (load_manifest_settings makes dozens).
    # Destroying it deletes their Tcl commands but leaves the queued scripts in the one shared interpreter,
    # named by Python object id + "<lambda>"; a later test's new lambda (for example the Enable/Disable Patches
    # button command) can get the same id, and the stale idle script then calls it during that test's mainloop:
    # the real apply's askyesno appeared in test_dry_run_from_the_window and hung it. Cancel them all first.
    # (Same fix as the VF2 REDUX patcher, commit e9317f8.)
    cancel_pending_after(tk_root)
    top.destroy()


def cancel_pending_after(root) -> None:
    for pending in root.tk.splitlist(root.tk.call("after", "info")):
        root.tk.call("after", "cancel", pending)


def labels_on_screen(widget):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Text)) or child.winfo_class() in ("TCheckbutton", "TLabel", "TButton", "Button", "TLabelframe"):
            try:
                out.append(child.cget("text"))
            except tk.TclError:
                out.append(child.get("1.0", "end-1c"))
        out.extend(labels_on_screen(child))
    return out


def test_window_has_the_vf2_sections_and_buttons(app):
    text = labels_on_screen(app.root)
    for expected in ["Patch Input", "Patch Settings", "Run Log", "Load Manifest Settings", "Defaults", "Enable All",
                     "Disable All", "Enable All Main Patches", "Enable all Optional Content",
                     "Dry Run (Validate Only)", "Enable/Disable Patches", "Restore Backup", "Check for updates",
                     gui.PROJECT_CREATOR_MESSAGE, gui.SAVE_COMPATIBILITY_NOTE, gui.AI_DISCLOSURE]:
        assert any(expected == t or expected in str(t) for t in text), expected
    root_frame = app.root.winfo_children()[0]
    assert [w.cget("text") for w in root_frame.winfo_children() if w.winfo_class() == "TLabelframe"] == ["Run Log"]
    tabs = [app.sections.tab(tab, "text") for tab in app.sections.tabs()]
    assert tabs == ["Patches", "Tools"], "the patch selection has its own tab, the tools another"
    patches_tab = app.root.nametowidget(app.sections.tabs()[0])
    assert [w.cget("text") for w in patches_tab.winfo_children() if w.winfo_class() == "TLabelframe"] == \
        ["Patch Input", "Patch Settings"]


def test_settings_load_under_their_category_with_descriptions(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    assert {k: v.get() for k, v in app.setting_vars.items()} == {
        "FixVanillaGameBugs": True, "OlderVillagerMortalityCurve": True, "PrivateRomanticTime": True,
        "UpTo28Children": False, "FamilyHistory": False, "AllowOlderPregnancies": True, "ClampMoneyAndFood": True, "SpecialUpgrades": True,
        "CheatUpgrades": True, "FleaMarket": True, "RollTheDice": True, "CustomMapImages": True,
        "VF2Songs": True, "GlowingCollectables": True, "BehaviorLabelVariants": True}
    text = labels_on_screen(app.settings_inner)
    assert text.index("Main Patches") < text.index("Fix Vanilla Game Bugs") < text.index("Optional Patches") \
        < text.index("Cheat Upgrades")
    assert "RollTheDice - default on - $500: a Popup Event happens right away." in text
    assert app.version_var.get() == "Version: dev"
    app.clear_all_settings()
    assert not any(v.get() for v in app.setting_vars.values())
    app.select_category_settings("main")
    assert app.selected_settings() == {"FixVanillaGameBugs", "OlderVillagerMortalityCurve", "PrivateRomanticTime",
                                      "AllowOlderPregnancies", "ClampMoneyAndFood", "SpecialUpgrades"}
    app.select_default_settings()
    assert len(app.selected_settings()) == 13 and "UpTo28Children" not in app.selected_settings()
    app.select_all_settings()                    # Enable All leaves the Experimental setting off
    assert len(app.selected_settings()) == 13 and "UpTo28Children" not in app.selected_settings()
    app.setting_vars["UpTo28Children"].set(True)  # ticked deliberately
    assert "UpTo28Children" in app.selected_settings()


def test_the_experimental_section_has_its_heading_and_warning(app):
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    headings = [w.cget("text") for w in app.settings_inner.winfo_children() if w.winfo_class() == "Label"]
    assert headings == ["Main Patches", "Optional Patches", "Experimental"]
    assert gui.EXPERIMENTAL_WARNING == "Experimental: not yet tested in a running game. Back up your saves before using it."
    texts = [getattr(w, "_vf1_description_text", "") for w in app.description_widgets]
    warning = "**" + gui.EXPERIMENTAL_WARNING + "**"
    assert warning in texts
    assert texts.index(warning) == len(texts) - 3, "the warning sits under the heading, before its settings"
    assert texts[-2].startswith("UpTo28Children - default off - ")
    assert texts[-1].startswith("FamilyHistory - default off - ")


def test_dependencies_tick_and_untick_together(app, tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["settings"].append({"id": "Extra", "label": "Extra", "default": False, "requires": ["CheatUpgrades"]})
    app.manifest_var.set(str(write_manifest(tmp_path / "m.json", settings=manifest["settings"])))
    assert app.load_manifest_settings()
    assert "Extra - default off **Requires: Cheat Upgrades.**" in \
        [w._vf1_description_text for w in app.description_widgets]
    app.setting_vars["CheatUpgrades"].set(False)
    app.setting_vars["Extra"].set(True)
    assert app.setting_vars["CheatUpgrades"].get()  # ticking Extra ticks what it needs
    app.setting_vars["CheatUpgrades"].set(False)
    assert not app.setting_vars["Extra"].get()  # unticking the prerequisite unticks Extra
    widget = next(w for w in app.description_widgets if "Extra" in w._vf1_description_text)
    bold = widget.tag_ranges("bold")
    assert widget.get(bold[0], bold[1]) == "Requires: Cheat Upgrades."


def test_a_closed_windows_queued_callbacks_never_reach_the_next_window(tk_root, tmp_path, monkeypatch):
    """The app fixture's teardown: without cancel_pending_after, a stale idle script of a closed window called the
    next window's Enable/Disable Patches command (start_apply(dry_run=False)) in 7 of 30 tries."""
    monkeypatch.setattr(gui, "local_settings_path", lambda base_dir=None: tmp_path / "local.json")
    monkeypatch.setattr(gui, "guess_game_dir", lambda: "")
    calls = []
    monkeypatch.setattr(gui.VF1PatcherGUI, "start_apply", lambda self, *, dry_run: calls.append(dry_run))
    for _ in range(20):
        top = tk.Toplevel(tk_root)
        top.withdraw()
        window = gui.VF1PatcherGUI(top)
        window.manifest_var.set(str(MANIFEST))
        assert window.load_manifest_settings()      # queues one after_idle(lambda) per markup label
        cancel_pending_after(tk_root)
        top.destroy()
        top = tk.Toplevel(tk_root)
        top.withdraw()
        gui.VF1PatcherGUI(top)
        tk_root.update()
        cancel_pending_after(tk_root)
        top.destroy()
    assert calls == []


def test_dry_run_from_the_window(app, workdir, vanilla_unchanged, monkeypatch):
    asked = []
    # A dry run never asks to Enable/Disable; if anything reaches the real apply, fail instead of hanging on it.
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    app.manifest_var.set(str(workdir / "patcher" / "manifest.json"))
    app.game_dir_var.set(str(vanilla_unchanged))
    app.output_dir_var.set(str(workdir / "out"))
    deadline = time.time() + 60

    def poll():
        if "running" in app.status_var.get() and time.time() < deadline:
            app.root.after(50, poll)
        else:
            app.root.quit()

    # The worker hands its result back with root.after, which needs mainloop.
    app.root.after(0, lambda: (app.start_apply(dry_run=True), poll()))
    app.root.mainloop()
    assert asked == [], "a dry run reached the Enable/Disable confirmation"
    assert app.status_var.get() == "Dry run complete.", app.log_text.get("1.0", "end")
    assert "Dry run complete. Nothing was written" in app.log_text.get("1.0", "end")
    assert not (workdir / "out").exists()


def test_output_folder_is_filled_in_from_the_vanilla_folder(app, tmp_path):
    app.manifest_var.set(str(MANIFEST))
    app.load_manifest_settings()
    app.game_dir_var.set(str(tmp_path / "Virtual Families"))
    app._auto_populate_output_dir()
    assert Path(app.output_dir_var.get()) == (tmp_path / "Virtual Families - Modded").resolve()


def test_settings_page_stays_far_below_the_windows_coordinate_limit(app):
    """The scrolled settings page must stay well under Windows' signed 16-bit coordinate limit (32,767 px),
    past which the Virtual Villagers patcher's window painted blank, even at 200% display scaling."""
    app.manifest_var.set(str(MANIFEST))
    assert app.load_manifest_settings()
    app.root.update_idletasks()
    assert app.settings_inner.winfo_reqheight() * 2 < 16000, app.settings_inner.winfo_reqheight()


def test_labels_that_are_not_laid_out_yet_do_not_freeze_the_window(app):
    """Counting wrapped lines in a text widget that has no width yet (hidden window) can take minutes."""
    app.manifest_var.set(str(MANIFEST))
    start = time.time()
    assert app.load_manifest_settings()
    app._resize_all_markup_labels()
    assert time.time() - start < 20

