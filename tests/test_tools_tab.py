"""The Tools tab: Back Up Saves and Restore Saves in the window (vf1_patcher_gui.py).

Everything runs against a fake Documents folder in tmp_path with a fake process list; message boxes
are answered by the test. No real save, game or process is touched.
"""
import tkinter as tk
from datetime import datetime, timedelta

import pytest

import vf1_patcher_gui as gui
import vf1_save_backup as sb


class NoProcesses:
    def find(self, exe_name):
        return []


class Running(NoProcesses):
    def find(self, exe_name):
        return [4242]


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
def documents(tmp_path):
    docs = tmp_path / "Documents"
    save = docs / "LDW" / "Virtual Families - Modded"
    (save / sb.PATCHER_DATA_FOLDER / "Children").mkdir(parents=True)
    (save / "Virtual Families - Modded1.ldw").write_bytes(b"slot one " * 20)
    (save / "Virtual Families - Modded2.ldw").write_bytes(b"slot two " * 20)
    (save / sb.PATCHER_DATA_FOLDER / "Slot 1.ini").write_text("[Slot]\nA=1\n")
    (save / sb.PATCHER_DATA_FOLDER / "Children" / "Virtual Families - Modded1.ldw.dat").write_bytes(b"kids")
    return docs


@pytest.fixture
def save(documents):
    return documents / "LDW" / "Virtual Families - Modded"


@pytest.fixture
def app(tk_root, tmp_path, documents, monkeypatch):
    monkeypatch.setattr(gui, "local_settings_path", lambda base_dir=None: tmp_path / "local.json")
    monkeypatch.setattr(gui, "guess_game_dir", lambda: "")
    monkeypatch.setattr(sb, "documents_folder", lambda: documents)
    monkeypatch.setattr(sb, "WindowsProcesses", NoProcesses)
    top = tk.Toplevel(tk_root)
    top.withdraw()
    window = gui.VF1PatcherGUI(top)
    window._open_work_wait = lambda label: None            # no popup during tests
    shown = []
    for name in ("showinfo", "showerror"):
        monkeypatch.setattr(gui.messagebox, name, lambda *a, _n=name, **k: shown.append((_n, a)))
    window.shown = shown
    yield window
    for pending in tk_root.tk.splitlist(tk_root.tk.call("after", "info")):
        tk_root.tk.call("after", "cancel", pending)
    top.destroy()


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def text_of(widget):
    return [w.cget("text") for w in walk(widget) if w.winfo_class() in ("TLabel", "TButton", "TCheckbutton", "Label")]


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and "Backups" not in p.relative_to(folder).parts}


def test_the_tools_tab_has_both_tools_each_with_a_question_mark(app):
    assert [app.sections.tab(t, "text") for t in app.sections.tabs()] == ["Patches", "Tools"]
    tools = app.root.nametowidget(app.sections.tabs()[1])
    shown = text_of(tools)
    for expected in ("Back Up Saves", "Restore Saves...", "Getting started"):
        assert expected in shown
    assert {"back_up_saves", "restore_saves"} <= app.help_keys
    assert app.saves_found_var.get() == "Save folders found: Virtual Families - Modded"


def test_the_found_line_says_when_there_are_no_saves(app, documents, save):
    import shutil
    shutil.rmtree(save)
    app._refresh_saves_found()
    assert "No modded save folders were found" in app.saves_found_var.get()


def test_no_documents_folder_is_reported_not_guessed(app, monkeypatch):
    monkeypatch.setattr(sb, "documents_folder", lambda: None)
    app.back_up_saves()
    app.restore_saves()
    assert [kind for kind, _ in app.shown] == ["showerror", "showerror"]
    assert all("Documents folder" in args[1] for _kind, args in app.shown)


def test_back_up_saves_pre_ticks_the_patchers_folder_and_backs_it_up(app, save):
    before = snapshot(save)
    dialog = app._show_backup_chooser(app._save_folders()[1])
    (folder, var), = dialog._vf1_choices
    assert folder == save and var.get() is True
    dialog._vf1_start()
    assert not dialog.winfo_exists()
    assert snapshot(save) == before                                    # the saves themselves are untouched
    backups = sb.list_backups(save)
    assert len(backups) == 1 and backups[0].file_count == 4 and backups[0].slots == [1, 2]
    assert snapshot(backups[0].path) == before
    assert app.status_var.get() == "Back Up Saves: 1 of 1 save folder(s) backed up."
    results = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert results and any("Backed up 4 file(s)" in t for t in text_of(results[-1]))
    results[-1].destroy()


def test_nothing_ticked_asks_for_a_choice_and_backs_nothing_up(app, save):
    dialog = app._show_backup_chooser(app._save_folders()[1])
    dialog._vf1_choices[0][1].set(False)
    dialog._vf1_start()
    assert app.shown[-1][0] == "showinfo" and "Tick at least one" in app.shown[-1][1][1]
    assert dialog.winfo_exists() and not (save / "Backups").exists()
    dialog.destroy()


def test_back_up_without_save_folders_says_so(app, save):
    import shutil
    shutil.rmtree(save)
    app.back_up_saves()
    assert app.shown[-1][0] == "showinfo" and "No modded save folders" in app.shown[-1][1][1]


def test_restore_without_backups_says_so(app):
    app.restore_saves()
    assert app.shown[-1][0] == "showinfo" and "no backups" in app.shown[-1][1][1]


def make_backup_then_damage(save):
    original = snapshot(save)
    backup = sb.back_up_save_folder(save, NoProcesses(), datetime(2026, 10, 24, 9, 0, 0)).backup_folder
    (save / "Virtual Families - Modded1.ldw").write_bytes(b"damaged")
    (save / "Virtual Families - Modded3.ldw").write_bytes(b"made later")
    return original, backup


def test_restore_never_replaces_without_confirming_and_backs_up_what_it_replaces(app, save, monkeypatch):
    original, backup = make_backup_then_damage(save)
    damaged = snapshot(save)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    dialog = app._show_restore_window(app._save_folders()[1])
    assert dialog._vf1_listbox.size() == 1 and "Save 1: (no name), Save 2: (no name)" in dialog._vf1_listbox.get(0)
    dialog._vf1_restore()
    assert len(asked) == 1 and "1 file(s) will be replaced, 0 added and 1 removed" in asked[0][1]
    assert "Replace: Virtual Families - Modded1.ldw" in asked[0][1] and "Remove: Virtual Families - Modded3.ldw" in asked[0][1]
    assert snapshot(save) == damaged, "declining the confirmation changed a file"
    assert len(sb.list_backups(save)) == 1

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    dialog._vf1_restore()
    assert snapshot(save) == original
    backups = sb.list_backups(save)
    assert [b.before_restore for b in backups] == [True, False]
    assert snapshot(backups[0].path) == damaged                       # what the restore replaced is kept
    assert app.shown[-1][0] == "showinfo" and "Your saves from before the restore are in" in app.shown[-1][1][1]
    assert dialog._vf1_listbox.size() == 2                           # the list refreshes with the safety backup
    dialog.destroy()


def test_restoring_one_slot_from_the_window(app, save, monkeypatch):
    original, _backup = make_backup_then_damage(save)
    (save / "Virtual Families - Modded2.ldw").write_bytes(b"slot two played on")
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    dialog = app._show_restore_window(app._save_folders()[1])
    dialog._vf1_scope.set("slot")
    assert dialog._vf1_slot_choice.get() == "Save 1: (no name)"
    dialog._vf1_restore()
    assert (save / "Virtual Families - Modded1.ldw").read_bytes() == original["Virtual Families - Modded1.ldw"]
    assert (save / "Virtual Families - Modded2.ldw").read_bytes() == b"slot two played on"
    dialog.destroy()


def test_restore_is_refused_while_the_game_is_running(app, save, monkeypatch):
    make_backup_then_damage(save)
    damaged = snapshot(save)
    monkeypatch.setattr(sb, "WindowsProcesses", Running)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    dialog = app._show_restore_window(app._save_folders()[1])
    dialog._vf1_restore()
    assert asked == [] and app.shown[-1][0] == "showerror" and "is running" in app.shown[-1][1][1]
    assert snapshot(save) == damaged
    dialog.destroy()


def test_delete_backup_asks_first(app, save, monkeypatch):
    make_backup_then_damage(save)
    answers = iter([False, True])
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: next(answers))
    dialog = app._show_restore_window(app._save_folders()[1])
    dialog._vf1_delete()
    assert len(sb.list_backups(save)) == 1
    dialog._vf1_delete()
    assert sb.list_backups(save) == []
    dialog.destroy()


def test_a_failed_backup_is_shown_as_not_backed_up(app, save, monkeypatch):
    def refuse(*args, **kwargs):
        raise sb.PauseRefused("Virtual Families - Modded.exe (process 1) is running but could not be paused")

    monkeypatch.setattr(sb, "back_up_save_folder", refuse)
    outcomes = app._run_backups([save])
    assert outcomes[0][1] is None and "could not be paused" in outcomes[0][2]
    assert app.status_var.get() == "Back Up Saves: 0 of 1 save folder(s) backed up."
    results = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert any("NOT backed up" in t for t in text_of(results[-1]))
    assert not (save / "Backups").exists()
    results[-1].destroy()


# ------------------------------------------------------------------ Rename Family


def real_form_saves(save):
    from test_rename_family import options_bytes, slot_bytes
    (save / "Virtual Families1.ldw").write_bytes(slot_bytes("Smith"))
    (save / "Virtual Families2.ldw").write_bytes(slot_bytes("Jones"))
    (save / "Virtual Families0.ldw").write_bytes(options_bytes(["Smith", "Jones", "", "", ""]))


def test_rename_family_is_on_the_tools_tab_with_a_question_mark(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    assert "Rename Family..." in text_of(tools) and "rename_family" in app.help_keys


def test_rename_family_without_family_saves_says_so(app, save):
    app.rename_family()                       # the fixture's saves are not in the game's format
    assert app.shown[-1][0] == "showinfo" and "No modded family saves" in app.shown[-1][1][1]


def test_rename_family_asks_then_renames_and_reports(app, save, monkeypatch):
    import vf1_rename_family as rf
    real_form_saves(save)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    monkeypatch.setattr(rf.save_backup, "WindowsProcesses", NoProcesses)
    dialog = app._show_rename_dialog(app._save_folders()[1])
    # Laid out as the Virtual Villagers patcher's Rename Tribe: a save folder, a list of families, a new name.
    assert dialog._vf1_folder_box.get() == "Virtual Families - Modded"
    assert dialog._vf1_slot_list.get(0, "end")[:2] == ("Save 1: Smith", "Save 2: Jones")
    assert dialog._vf1_slot_list.curselection() == (0,) and dialog._vf1_name_var.get() == ""
    assert dialog._vf1_counter_var.get() == f"0 / {rf.MAX_LENGTH} characters"
    assert str(dialog._vf1_rename_button.cget("state")) == "disabled"
    dialog._vf1_name_var.set("Smith")
    assert "already" in dialog._vf1_problem_var.get()
    dialog._vf1_name_var.set("x" * 20)
    assert "too long" in dialog._vf1_problem_var.get() and dialog._vf1_counter_var.get() == "20 / 19 characters"
    assert str(dialog._vf1_rename_button.cget("state")) == "disabled"
    dialog._vf1_start()
    assert dialog.winfo_exists() and not asked and app.shown[-1][0] == "showerror"     # refused before asking
    dialog._vf1_choose(1)
    dialog._vf1_name_var.set("The Joneses")
    assert dialog._vf1_problem_var.get() == "" and str(dialog._vf1_rename_button.cget("state")) == "normal"
    dialog._vf1_start()
    assert len(asked) == 1 and '"Jones" (Save 2)' in asked[0][1] and "The Joneses" in asked[0][1]
    assert dialog.winfo_exists()                                    # it stays open, as Rename Tribe does
    assert {s.slot: s.name for s in rf.read_slots(save)}[2] == "The Joneses"
    assert {s.slot: s.name for s in rf.read_slots(save)}[1] == "Smith"
    assert app.status_var.get() == "Rename Family: Jones is now The Joneses."
    assert app.shown[-1][0] == "showinfo" and "(before rename)" in app.shown[-1][1][1]
    assert '"Jones" is now "The Joneses" (Save 2, Virtual Families - Modded)' in app.shown[-1][1][1]
    assert dialog._vf1_slot_list.get(1) == "Save 2: The Joneses" and dialog._vf1_name_var.get() == ""
    assert sb.list_backups(save)[0].before_rename
    dialog.destroy()


def test_declining_the_confirmation_changes_nothing(app, save, monkeypatch):
    real_form_saves(save)
    before = snapshot(save)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    dialog = app._show_rename_dialog(app._save_folders()[1])
    dialog._vf1_name_var.set("Nope")
    dialog._vf1_start()
    assert snapshot(save) == before and dialog.winfo_exists() and not (save / "Backups").exists()
    dialog.destroy()


def test_a_running_game_is_reported_and_nothing_changes(app, save, monkeypatch):
    import vf1_rename_family as rf
    real_form_saves(save)
    before = snapshot(save)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(rf.save_backup, "WindowsProcesses", Running)
    dialog = app._show_rename_dialog(app._save_folders()[1])
    dialog._vf1_name_var.set("Other")
    dialog._vf1_start()
    assert snapshot(save) == before
    assert app.shown[-1][0] == "showerror" and "Close the game first" in app.shown[-1][1][1]
    assert app.status_var.get() == "Rename Family: nothing was renamed."
    dialog.destroy()


# ------------------------------------------------------------------ Copy Player Slot


def copy_form_saves(save):
    """Smith in Save 1, Jones in Save 2, Saves 3 to 5 empty (their menu flags clear)."""
    import vf1_copy_slot as cs
    from test_rename_family import options_bytes, slot_bytes
    (save / "Virtual Families1.ldw").write_bytes(slot_bytes("Smith"))
    (save / "Virtual Families2.ldw").write_bytes(slot_bytes("Jones"))
    options = bytearray(options_bytes(["Smith", "Jones", "", "", ""]))
    for slot in (1, 2):
        options[cs._used_offset(bytes(options), slot)] = 1
    (save / "Virtual Families0.ldw").write_bytes(bytes(options))


def test_copy_player_slot_is_on_the_tools_tab_with_a_question_mark(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    assert "Copy Player Slot..." in text_of(tools) and "copy_player_slot" in app.help_keys


def test_copy_player_slot_without_family_saves_says_so(app, save):
    app.copy_player_slot()
    assert app.shown[-1][0] == "showinfo" and "No modded family saves" in app.shown[-1][1][1]


def test_copy_player_slot_asks_then_copies_and_reports(app, save, monkeypatch):
    import vf1_copy_slot as cs
    import vf1_rename_family as rf
    copy_form_saves(save)
    asked = []
    monkeypatch.setattr(app, "_ask_copy", lambda parent, text: asked.append(text) or True)
    monkeypatch.setattr(cs.save_backup, "WindowsProcesses", NoProcesses)
    dialog = app._show_copy_dialog(app._save_folders()[1])
    assert dialog._vf1_folder_box.get() == "Virtual Families - Modded"
    assert dialog._vf1_source_list.get(0, "end") == ("Save 1: Smith", "Save 2: Jones")
    assert dialog._vf1_target_list.get(0, "end") == ("Save 3: (empty)", "Save 4: (empty)", "Save 5: (empty)")
    assert dialog._vf1_counter_var.get() == f"0 / {rf.MAX_LENGTH} characters"
    assert str(dialog._vf1_copy_button.cget("state")) == "disabled"
    dialog._vf1_name_var.set("x" * 20)
    assert "too long" in dialog._vf1_problem_var.get() and str(dialog._vf1_copy_button.cget("state")) == "disabled"
    dialog._vf1_choose(1, 1)
    dialog._vf1_name_var.set("Jones Two")
    assert dialog._vf1_problem_var.get() == "" and str(dialog._vf1_copy_button.cget("state")) == "normal"
    dialog._vf1_start()
    assert asked == [gui.copy_prompt_text("Jones", 2, 4, "Jones Two", save)]
    assert dialog.winfo_exists()
    names = {s.slot: s.name for s in cs.read_slots(save)}
    assert names[4] == "Jones Two" and names[2] == "Jones" and names[1] == "Smith"
    assert app.status_var.get() == "Copy Player Slot: Jones was copied to Save 4 as Jones Two."
    assert app.shown[-1][0] == "showinfo" and "(before copy)" in app.shown[-1][1][1]
    assert dialog._vf1_source_list.get(0, "end")[-1] == "Save 4: Jones Two"
    assert dialog._vf1_target_list.get(0, "end") == ("Save 3: (empty)", "Save 5: (empty)")
    assert sb.list_backups(save)[0].before_copy
    dialog.destroy()


def test_copy_player_slot_with_no_empty_slot_says_so(app, save):
    import vf1_copy_slot as cs
    copy_form_saves(save)
    options = bytearray((save / "Virtual Families0.ldw").read_bytes())
    for slot in (3, 4, 5):
        options[cs._used_offset(bytes(options), slot)] = 1
    (save / "Virtual Families0.ldw").write_bytes(bytes(options))
    dialog = app._show_copy_dialog(app._save_folders()[1])
    dialog._vf1_name_var.set("Other")
    assert "Every save slot is in use" in dialog._vf1_problem_var.get()
    assert str(dialog._vf1_copy_button.cget("state")) == "disabled"
    dialog.destroy()


def test_the_copy_prompt_names_everything_and_no_is_the_default(app, save):
    text = gui.copy_prompt_text("Smith", 1, 4, "Smith Two", save)
    assert text.startswith('Copy the family "Smith" from Save 1 into Save 4, as "Smith Two"?')
    assert f"Save folder: {save}" in text and "backed up first" in text and "(before copy)" in text
    host = tk.Toplevel(app.root)              # a shown window, as the Copy Player Slot window is
    host.update()
    for key in ("<Return>", "<Escape>"):
        prompt = app._copy_prompt(host, text)
        prompt.update()
        assert prompt._vf1_text == text and str(prompt._vf1_no.cget("default")) == "active"
        prompt._vf1_no.focus_force()          # a key goes to the window with the focus
        prompt.update()
        assert prompt.focus_get() is prompt._vf1_no
        prompt._vf1_no.event_generate(key)
        prompt.update()
        assert prompt._vf1_answer == {"yes": False} and not prompt.winfo_exists()
    prompt = app._copy_prompt(host, text)
    prompt._vf1_yes.invoke()
    assert prompt._vf1_answer == {"yes": True}
    host.destroy()


def test_copy_player_slot_declined_or_running_changes_nothing(app, save, monkeypatch):
    import vf1_copy_slot as cs
    copy_form_saves(save)
    before = snapshot(save)
    asked = []

    host = tk.Toplevel(app.root)              # shown, so the prompt can take the focus (the tests' window is hidden)
    host.update()

    def say_no(parent, text):                 # the real prompt, answered with Return (No, the default)
        prompt = app._copy_prompt(host, text)
        asked.append(prompt._vf1_text)
        prompt._vf1_no.focus_force()
        prompt.update()
        prompt._vf1_no.event_generate("<Return>")
        prompt.update()
        assert not prompt.winfo_exists()      # Return closed it
        return prompt._vf1_answer["yes"]

    monkeypatch.setattr(app, "_ask_copy", say_no)
    dialog = app._show_copy_dialog(app._save_folders()[1])
    dialog._vf1_name_var.set("Nope")
    dialog._vf1_start()
    assert asked == [gui.copy_prompt_text("Smith", 1, 3, "Nope", save)]
    assert snapshot(save) == before and not (save / "Backups").exists() and dialog.winfo_exists()
    monkeypatch.setattr(app, "_ask_copy", lambda parent, text: True)
    monkeypatch.setattr(cs.save_backup, "WindowsProcesses", Running)
    dialog._vf1_start()
    assert snapshot(save) == before and not (save / "Backups").exists()
    assert app.shown[-1][0] == "showerror" and "Close the game first" in app.shown[-1][1][1]
    assert app.status_var.get() == "Copy Player Slot: nothing was copied."
    dialog.destroy()
    host.destroy()


# ------------------------------------------------------------------ Game Speed


def speed_saves(save):
    from test_game_speed import NORMAL_SAVE, PAUSED_SAVE, fixture
    (save / "Virtual Families1.ldw").write_bytes(fixture(PAUSED_SAVE))
    (save / "Virtual Families2.ldw").write_bytes(fixture(NORMAL_SAVE))


def test_game_speed_is_on_the_tools_tab_with_a_question_mark(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    assert "Game Speed..." in text_of(tools) and "game_speed" in app.help_keys


def test_game_speed_without_family_saves_says_so(app, save):
    app.game_speed()
    assert app.shown[-1][0] == "showinfo" and "No modded family saves" in app.shown[-1][1][1]


def test_game_speed_shows_each_speed_asks_then_sets_it(app, save, monkeypatch):
    import vf1_game_speed as gsp
    speed_saves(save)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    dialog = app._show_speed_dialog(app._save_folders()[1])
    labels = dialog._vf1_slot_list.get(0, "end")
    assert labels[0].startswith("Save 1: ") and labels[0].endswith("- Paused")
    assert labels[1].startswith("Save 2: ") and labels[1].endswith("- Normal")
    assert dialog._vf1_slot_list.curselection() == (0,) and dialog._vf1_target_var.get() == "Normal"
    dialog._vf1_target_var.set("Paused")
    assert "already" in dialog._vf1_problem_var.get() and str(dialog._vf1_set_button.cget("state")) == "disabled"
    dialog._vf1_start()
    assert dialog.winfo_exists() and not asked                       # refused before asking
    dialog._vf1_choose(1)
    assert dialog._vf1_target_var.get() == "Paused" and dialog._vf1_problem_var.get() == ""
    dialog._vf1_start()
    assert len(asked) == 1 and "(Save 2)" in asked[0][1] and "from Normal to Paused" in asked[0][1]
    assert {s.slot: s.state.label for s in gsp.read_slots(save) if s.state}[2] == "Paused"
    assert app.status_var.get() == "Game Speed: Save 2 is now Paused."
    assert app.shown[-1][0] == "showinfo" and "(before speed change)" in app.shown[-1][1][1]
    assert dialog.winfo_exists() and dialog._vf1_slot_list.get(1).endswith("- Paused")
    assert sb.list_backups(save)[0].before_speed_change
    dialog.destroy()


def test_game_speed_with_the_game_running_changes_nothing(app, save, monkeypatch):
    speed_saves(save)
    before = snapshot(save)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(sb, "WindowsProcesses", Running)
    dialog = app._show_speed_dialog(app._save_folders()[1])
    dialog._vf1_start()
    assert snapshot(save) == before
    assert app.shown[-1][0] == "showerror" and "Close the game first" in app.shown[-1][1][1]
    assert app.status_var.get() == "Game Speed: nothing was changed."
    dialog.destroy()


# ------------------------------------------------------------------ Family Tree Maker


def test_the_family_tree_maker_is_on_the_tools_tab_with_a_question_mark(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    assert "Family Tree Maker..." in text_of(tools) and "family_tree" in app.help_keys


def test_the_tools_tab_is_laid_out_as_the_virtual_villagers_patchers(app):
    """One box for the game: the save folders found, then the save tools in a row and the family and game tools in
    the next, each link with its "?"; no Refresh link (the line is read again whenever the tab is shown)."""
    tools = app.root.nametowidget(app.sections.tabs()[1])
    links = [w.cget("text") for w in walk(tools) if w.winfo_class() == "TLabel" and str(w.cget("style")) == "Link.TLabel"]
    assert links == ["Back Up Saves", "Restore Saves...", "Rename Family...", "Copy Player Slot...", "Game Speed...", "Family Tree Maker...",
                     "Game Mechanics...", "Getting started"]
    assert "Refresh" not in text_of(tools)
    boxes = [w.cget("text") for w in walk(tools) if w.winfo_class() == "TLabelframe"]
    assert boxes == [gui.TOOLS_GAME_TITLE, "How to Use"]
