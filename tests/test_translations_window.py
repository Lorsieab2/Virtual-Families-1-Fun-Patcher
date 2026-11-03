"""The Translations window and its helpers (patcher/vf1_translations_window.py, patcher/vf1_translations.py): the
language list (native names) and the choice written into the modded copies (applies at the next game start, no
re-patching), adding (button and drag and drop share one handler), export, the editor's autosave, progress,
filters, protected placeholders, person choices and "English changed" marks, and Share on GitHub.  Ported from the
Fish and Plant Tycoon Fix Patcher's tests/test_translations_window.py."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from unittest import mock
import urllib.parse

import pytest

from conftest import ROOT

import translation_format as tfmt
import vf1_translations as tr
import vf1_translations_window as tw

FOLDER = "Virtual Families 1 Patcher Files"
ENTRIES = [tfmt.Entry(tfmt.make_key("strings", "1050", "Done"), "Done"),
           tfmt.Entry(tfmt.make_key("strings", "4", "Continue"), "Continue"),
           tfmt.Entry(tfmt.make_key("strings", "940", "{name} is sick. {He/She} needs a doctor."),
                      "{name} is sick. {He/She} needs a doctor.")]


def write_translation(folder: Path, language: str, translator: str = "", translations=("Terminé", "", "")) -> Path:
    f = tfmt.new_file("vf1", ENTRIES, language, "fr", translator)
    for row, text in zip(f.rows, translations):
        row.translation = text
    path = folder / tfmt.file_name(tfmt.GAME_TITLES["vf1"], language)
    path.write_bytes(tfmt.to_bytes(f))
    return path


def modded_copy(tmp: Path) -> Path:
    copy = tmp / "Virtual Families - Modded"
    (copy / FOLDER).mkdir(parents=True)
    (copy / FOLDER / "vf1tr.dll").write_bytes(b"MZ")
    return copy


# ---------------------------------------------------------------------------------------------- texts


def test_texts():
    assert tr.SHARE_INVITE == ("If you want to share your translation, consider going to the Patcher's GitHub page "
                               "and adding it!")
    assert tfmt.EMAIL_MESSAGE in tr.CREDIT_HINT
    text = " ".join(tw.HELP[1])
    assert "GitHub account" in text and "https://github.com/signup" in text and tfmt.EMAIL_MESSAGE in text
    assert "{il/elle}" in text


def test_languages_show_their_own_names():
    names = dict(tr.LANGUAGES)
    for native in ("Français", "Deutsch", "Español", "Русский", "日本語", "Türkçe", "Polski"):
        assert native in names
    assert "French" not in names and "German" not in names


def test_issue_url():
    url = tr.issue_url("vf1", "Français", 42.4)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["template"] == ["translation.yml"]
    assert query["game"] == ["Virtual Families"] and query["language"] == ["Français"]
    assert query["coverage"] == ["42%"]
    assert "@" not in urllib.parse.unquote(url)


def test_the_tools_tab_has_the_window():
    source = (ROOT / "patcher" / "vf1_patcher_gui.py").read_text(encoding="utf-8")
    assert '"Translations...", self.translations' in source and "def translations(self)" in source
    how = json.loads((ROOT / "patcher" / "how_to_use.json").read_text(encoding="utf-8"))
    assert "translations" in json.dumps(how)


def test_the_setting_installs_the_dll_and_vf1fun_loads_it_last():
    manifest = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8"))
    setting = next(s for s in manifest["settings"] if s["id"] == "Translations")
    assert setting["default"] is True
    assert setting["files"] == [{"source": "vf1tr.dll", "target": f"{FOLDER}/vf1tr.dll"}]
    cpp = (ROOT / "native" / "vf1fun" / "vf1fun.cpp").read_text(encoding="utf-8")
    startup = cpp[cpp.index("void __cdecl VF1Fun_Startup()"):]
    startup = startup[:startup.index("\n}\n")]
    assert startup.rstrip().endswith("LoadTranslationsCompanion();")          # after vf1text.dll / vf1font.dll
    assert 'L"vf1tr.dll"' in cpp and '"VF1Tr_Startup"' in cpp


# ---------------------------------------------------------------------------------------------- the choice


def test_installed_and_labels(tmp_path):
    folder = tmp_path / "translations"
    folder.mkdir()
    write_translation(folder, "Français", "Ann")
    (folder / "vf1").mkdir()
    write_translation(folder / "vf1", "Deutsch", "Bob")
    items = tr.installed("vf1", folder)
    assert [i.label for i in items] == ["Deutsch (by Bob)", "Français (by Ann)"]
    assert items[0].shipped and not items[1].shipped


def test_choosing_writes_every_copy_and_english_removes_it(tmp_path):
    folder = tmp_path / "translations"
    folder.mkdir()
    copy = modded_copy(tmp_path)
    choices = tmp_path / "choice.json"
    path = write_translation(folder, "Français")
    written = tr.apply_choice("vf1", path, [str(tmp_path / "Virtual Families")], choices, folder)
    assert written == [copy.resolve()]
    ini = (copy / FOLDER / "Translation.ini").read_bytes().decode("utf-8-sig")
    assert "language=Français" in ini and f"file={path.resolve()}" in ini
    assert (copy / FOLDER / "Translation.txt").read_bytes() == path.read_bytes()
    assert tr.load_choices(choices)["vf1"] == path.name
    tr.apply_choice("vf1", None, [str(copy)], choices, folder)
    assert not (copy / FOLDER / "Translation.ini").exists()
    assert tr.load_choices(choices)["vf1"] == ""


def test_a_copy_without_the_dll_is_left_alone(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    folder = tmp_path / "translations"
    folder.mkdir()
    path = write_translation(folder, "Français")
    assert not tr.write_choice(plain, "vf1", path, "Français")
    assert list(plain.iterdir()) == []


def test_install_refuses_email_and_other_games(tmp_path):
    folder = tmp_path / "translations"
    bad = write_translation(tmp_path, "Français", translations=("Terminé : écrivez à a@b.com", "", ""))
    with pytest.raises(tr.TranslationProblem) as caught:
        tr.install_file(bad, "vf1", ENTRIES, folder)
    assert tfmt.EMAIL_MESSAGE in str(caught.value) and "a@b.com" not in str(caught.value)
    other = tmp_path / "other.txt"
    other.write_bytes(bad.read_bytes().replace(b"@game\tVirtual Families", b"@game\tFish Tycoon"))
    with pytest.raises(tr.TranslationProblem):
        tr.install_file(other, "vf1", ENTRIES, folder)
    good = write_translation(tmp_path, "Polski")
    target, report = tr.install_file(good, "vf1", ENTRIES, folder)
    assert target == folder / "Virtual Families - Polski.txt"
    assert report.coverage == pytest.approx(100 / 3)


def test_a_new_patch_gets_the_chosen_language(tmp_path):
    copy = modded_copy(tmp_path)
    folder = tmp_path / "translations"
    folder.mkdir()
    path = write_translation(folder, "Italiano")
    with mock.patch.object(tr, "TRANSLATIONS_DIR", folder), mock.patch.object(tr, "CHOICE_PATH", tmp_path / "c.json"):
        tr.save_choices({"vf1": path.name})
        assert tr.write_choice_into(copy, "vf1")
    assert "language=Italiano" in (copy / FOLDER / "Translation.ini").read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------------------------- the window


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk: {exc}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def window(root, tmp_path):
    folder = tmp_path / "translations"
    folder.mkdir()
    copy = modded_copy(tmp_path)
    path = write_translation(folder, "Français", "Ann")
    w = tw.TranslationsWindow(root, "vf1", {"vf1": [str(copy)]}, folder=folder, choices_path=tmp_path / "choice.json")
    w.entries_cache["vf1"] = ENTRIES
    w.test = {"folder": folder, "copy": copy, "path": path, "tmp": tmp_path}
    yield w
    if w.window.winfo_exists():
        w.close()


def test_dropdown_and_choice(window):
    values = list(window.language_box.cget("values"))
    assert values == ["English (original)", "Français (by Ann)"]
    window.language_var.set(values[1])
    assert window.choose() == [window.test["copy"].resolve()]
    assert "next start" in window.choice_status.get() and "No patching needed" in window.choice_status.get()


def test_drop_and_button_share_one_handler(window):
    if window.drop.active:
        assert window.drop.handler == window.add_files
    other = write_translation(window.test["tmp"], "Deutsch")
    with mock.patch.object(tw.messagebox, "showinfo") as info:
        added = window.add_files([other])
    assert added == [window.test["folder"] / "Virtual Families - Deutsch.txt"]
    assert "Coverage" in info.call_args[0][1]
    assert len(window.items) == 2


def test_export(window):
    window.listbox.selection_set(1)                                        # row 0 is English (original)
    target = window.test["tmp"] / "exported.txt"
    with mock.patch.object(tw.filedialog, "asksaveasfilename", return_value=str(target)):
        assert window.export() == [target]
    assert target.read_bytes() == window.test["path"].read_bytes()


def test_share_no_does_nothing(window):
    window.listbox.selection_set(1)
    with mock.patch.object(tw.messagebox, "askyesno", return_value=False) as ask, \
            mock.patch.object(tw.webbrowser, "open") as browser, \
            mock.patch.object(tw.TranslationsWindow, "_show_in_folder") as shown, \
            mock.patch.object(tw, "CreditDialog") as credit:
        assert window.share() is None
    assert ask.call_args[0][1] == tr.SHARE_CONFIRMATION
    assert ask.call_args[1]["default"] == "no"
    browser.assert_not_called()
    shown.assert_not_called()
    credit.assert_not_called()
    assert not (window.test["folder"] / "Shared").exists()


def test_share_yes_credit_typed_then_export_and_github(window):
    window.listbox.selection_set(1)
    seen = {}

    def answer(dialog):
        seen["initial"] = dialog.var.get()
        dialog.var.set("me@example.com")
        dialog.ok()
        seen["email_refused"] = dialog.error.get()
        dialog.var.set("")
        dialog.ok()
        seen["empty_refused"] = dialog.error.get()
        dialog.var.set("Ann Lee")
        dialog.ok()
    tw.CreditDialog.test_answer = answer
    try:
        with mock.patch.dict(os.environ, {"USERNAME": "WindowsUser", "GIT_AUTHOR_NAME": "Git Name"}), \
                mock.patch.object(tw.messagebox, "askyesno", return_value=True), \
                mock.patch.object(tw.messagebox, "showinfo"), \
                mock.patch.object(tw.webbrowser, "open") as browser, \
                mock.patch.object(tw.TranslationsWindow, "_show_in_folder") as shown:
            url = window.share()
    finally:
        tw.CreditDialog.test_answer = None
    assert seen["initial"] == ""                                           # never filled in
    assert tfmt.EMAIL_MESSAGE in seen["email_refused"]
    assert "required" in seen["empty_refused"]
    browser.assert_called_once_with(url)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert (query["game"], query["language"]) == (["Virtual Families"], ["Français"])
    exported = shown.call_args[0][0]
    assert tfmt.parse_bytes(exported.read_bytes(), "vf1").translator == "Ann Lee"
    assert b"@example" not in exported.read_bytes() and b"WindowsUser" not in exported.read_bytes()


def test_editor_autosave_progress_filter_and_person_choice(window):
    editor = window.open_editor(window.test["path"])
    assert editor.progress.get() == "1 of 3 lines translated (33%)"
    editor.untranslated_only.set(True)
    editor.fill()
    assert [r.english for r in editor.visible.values()] == ["Continue", "{name} is sick. {He/She} needs a doctor."]
    iid = next(i for i, r in editor.visible.items() if r.english.startswith("{name}"))
    editor.tree.selection_set(iid)
    editor.show_row()
    buttons = [b.cget("text") for b in editor.insert_row.winfo_children()]
    assert "Insert {name}" in buttons and "Insert {il/elle}" in buttons
    editor.translation_text.insert("1.0", "{nom} est malade.")
    editor.changed()
    assert "will show English" in editor.message.get()                     # {name} must stay
    editor.translation_text.delete("1.0", "end")
    editor.translation_text.insert("1.0", "{name} est {name: m=malade | f=malade}. {Il/Elle} doit voir un médecin.")
    editor.changed()
    assert editor.message.get() == "OK"
    assert editor.translation_text.tag_ranges("placeholder")               # placeholders shown in colour
    editor.save()
    parsed = tfmt.parse_bytes(window.test["path"].read_bytes(), "vf1")
    assert len(parsed.translations()) == 2
    assert editor.progress.get() == "2 of 3 lines translated (67%)"
    editor.close()


def test_editor_marks_new_and_changed_lines_after_an_update(window):
    changed = tfmt.Entry(tfmt.make_key("strings", "1050", "Done!"), "Done!")
    newer = [changed] + ENTRIES[1:] + [tfmt.Entry(tfmt.make_key("strings", "2", "Status: "), "Status: ")]
    window.entries_cache["vf1"] = newer
    editor = window.open_editor(window.test["path"])
    assert "1 new line" in editor.update_note and "1 with changed English" in editor.update_note
    statuses = {r.english: editor.status(r) for r in editor.file.rows}
    assert statuses["Done"] == "changed" and statuses["Done!"] == "new"   # the old translation kept beside it
    old = next(r for r in editor.file.rows if r.english == "Done")
    assert old.translation == "Terminé"
    assert editor.STATUS["changed"] == "English changed"
    editor.close()


# ---------------------------------------------------------------------------------------------- several at once


def more_translations(window):
    """Rows: 0 English (original), 1 Français (by Zed) (came with the patcher), 2 Deutsch (by Bob), 3 Français (by Ann)."""
    folder = window.test["folder"]
    (folder / "vf1").mkdir()
    shipped = write_translation(folder / "vf1", "Français", "Zed")
    deutsch = write_translation(folder, "Deutsch", "Bob")
    window.refresh()
    window.window.update()
    assert [i.label for i in window.items] == ["Français (by Zed)", "Deutsch (by Bob)", "Français (by Ann)"]
    return shipped, deutsch, window.test["path"]


def click(listbox, row, modifier=""):
    """A synthetic Tk click on a row (Tk's own Listbox bindings do the selecting; the real mouse never moves)."""
    listbox.update()
    x, y, width, height = listbox.bbox(row)
    for event in (f"<{modifier}Button-1>", f"<{modifier}ButtonRelease-1>"):
        listbox.event_generate(event, x=x + width // 2, y=y + height // 2)
    listbox.update()


def button(window, text):
    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)
    return next(w for w in walk(window.window) if w.winfo_class() == "TButton" and w.cget("text") == text)


def test_the_list_is_multi_select_click_ctrl_and_shift(window):
    more_translations(window)
    box = window.listbox
    assert box.cget("selectmode") == "extended" and not int(box.cget("exportselection"))
    assert box.get(0).startswith("English (original)")
    click(box, 1)
    assert box.curselection() == (1,)
    click(box, 3, "Shift-")                                                # a range
    assert box.curselection() == (1, 2, 3)
    click(box, 2, "Control-")                                              # Ctrl+click takes one out...
    assert box.curselection() == (1, 3)
    click(box, 0, "Control-")                                              # ...and puts one in
    assert box.curselection() == (0, 1, 3)
    assert [i.label for i in window.selected_items()] == ["Français (by Zed)", "Français (by Ann)"]
    assert window.english_selected()
    assert window.selected() is None                                       # Edit and Check want one
    click(box, 2)                                                          # a plain click selects only that one
    assert box.curselection() == (2,)
    assert window.selected().label == "Deutsch (by Bob)"
    assert window.language_var.get() == "English (original)"               # selecting never chooses the language


def test_select_all_button_and_ctrl_a(window):
    more_translations(window)
    box = window.listbox
    button(window, "Select All").invoke()
    assert box.curselection() == (0, 1, 2, 3)
    box.selection_clear(0, "end")
    for sequence in ("<Control-a>", "<Control-A>"):
        assert box.bind(sequence) and window.window.bind(sequence)
    box.focus_force()
    box.update()
    box.event_generate("<Control-a>")
    box.update()
    if box.curselection() != (0, 1, 2, 3):                                 # no keyboard focus on this desktop
        assert window._select_all_key() == "break"
    assert box.curselection() == (0, 1, 2, 3)
    assert window.language_var.get() == "English (original)"


def test_delete_prompt_lists_the_files_and_no_does_nothing(window):
    shipped, deutsch, francais = more_translations(window)
    window.select_all()
    with mock.patch.object(tw.messagebox, "askyesno", return_value=False) as ask, \
            mock.patch.object(tr, "recycle") as recycle:
        assert window.delete() == []
    recycle.assert_not_called()
    assert shipped.exists() and deutsch.exists() and francais.exists()
    assert ask.call_count == 1
    assert ask.call_args[1]["default"] == "no"
    text = ask.call_args[0][1]
    assert text.startswith("Delete these 3 translations?") and "Windows Recycle Bin" in text
    for name in ("Français (by Zed)", "Deutsch (by Bob)", "Français (by Ann)", deutsch.name, francais.name):
        assert name in text
    assert "comes back with the next patcher update" in text               # one came with the patcher
    assert "English (original) is part of the game and cannot be deleted: it is skipped." in text
    assert "language in the game now" not in text                          # English is the language
    assert len(window.items) == 3 and window.listbox.curselection() == (0, 1, 2, 3)


def test_delete_without_shipped_or_english_says_neither(window):
    _shipped, deutsch, _francais = more_translations(window)
    window.listbox.selection_set(2)
    with mock.patch.object(tw.messagebox, "askyesno", return_value=False) as ask:
        window.delete()
    text = ask.call_args[0][1]
    assert text.startswith("Delete this translation?") and deutsch.name in text
    assert "patcher update" not in text and "cannot be deleted" not in text


def test_delete_english_only_asks_nothing(window):
    window.listbox.selection_set(0)
    with mock.patch.object(tw.messagebox, "askyesno") as ask, mock.patch.object(tw.messagebox, "showinfo") as info, \
            mock.patch.object(tr, "recycle") as recycle:
        assert window.delete() == []
    ask.assert_not_called()
    recycle.assert_not_called()
    assert "cannot be deleted" in info.call_args[0][1]


def recycled(paths):
    for path in paths:
        Path(path).unlink()                    # stands in for the Recycle Bin


def test_delete_yes_recycles_exactly_the_selected_files_and_skips_english(window):
    shipped, deutsch, francais = more_translations(window)
    window.listbox.selection_set(0)
    window.listbox.selection_set(1)
    window.listbox.selection_set(2)
    with mock.patch.object(tw.messagebox, "askyesno", return_value=True), \
            mock.patch.object(tr, "recycle", side_effect=recycled) as recycle:
        assert window.delete() == [shipped, deutsch]
    recycle.assert_called_once_with([shipped, deutsch])                    # English (original) is not a file
    assert not shipped.exists() and not deutsch.exists() and francais.exists()
    assert [i.label for i in window.items] == ["Français (by Ann)"]
    assert window.listbox.get(0).startswith("English (original)") and window.listbox.size() == 2


def test_deleting_the_language_in_the_game_goes_back_to_english(window):
    _shipped, _deutsch, francais = more_translations(window)
    window.language_var.set("Français (by Ann)")
    copy = window.test["copy"]
    assert window.choose() == [copy.resolve()]
    assert (copy / FOLDER / "Translation.ini").exists()
    editor = window.open_editor(francais)
    window.listbox.selection_set(3)
    with mock.patch.object(tw.messagebox, "askyesno", return_value=True) as ask, \
            mock.patch.object(tr, "recycle", side_effect=recycled):
        assert window.delete() == [francais]
    assert "Français (by Ann) is the language in the game now: the game goes back to English (original) from its " \
           "next start." in ask.call_args[0][1]
    assert window.language_var.get() == "English (original)"
    assert tr.load_choices(window.choices_path)["vf1"] == ""               # as choosing English does
    assert not (copy / FOLDER / "Translation.ini").exists() and not (copy / FOLDER / "Translation.txt").exists()
    assert "English" in window.choice_status.get() and "next start" in window.choice_status.get()
    assert editor not in window.editors and not editor.window.winfo_exists()
    window.close()
    assert not francais.exists()                                           # the closed editor did not save it back


def test_recycle_bin_failure_deletes_nothing(window):
    shipped, deutsch, francais = more_translations(window)
    window.language_var.set("Français (by Ann)")
    window.choose()
    window.select_all()
    with mock.patch.object(tw.messagebox, "askyesno", return_value=True), \
            mock.patch.object(tw.messagebox, "showerror") as error, \
            mock.patch.object(tr, "recycle", side_effect=OSError("The Recycle Bin is not available.")):
        assert window.delete() == []
    assert "Nothing was deleted" in error.call_args[0][1] and "Recycle Bin is not available" in error.call_args[0][1]
    assert shipped.exists() and deutsch.exists() and francais.exists()
    assert len(window.items) == 3
    assert window.language_var.get() == "Français (by Ann)"
    assert tr.load_choices(window.choices_path)["vf1"] == francais.name
    assert (window.test["copy"] / FOLDER / "Translation.ini").exists()


def test_export_several_one_file_each(window):
    shipped, deutsch, francais = more_translations(window)
    window.select_all()                                                    # English (original) is not exported
    out = window.test["tmp"] / "out"
    out.mkdir()
    with mock.patch.object(tw.filedialog, "askdirectory", return_value=str(out)) as folder, \
            mock.patch.object(tw.filedialog, "asksaveasfilename") as save_as, \
            mock.patch.object(tw.messagebox, "showinfo") as info:
        written = window.export()
    folder.assert_called_once()
    save_as.assert_not_called()
    assert written == [out / shipped.name, out / deutsch.name, out / "Virtual Families - Français (2).txt"]
    assert [p.read_bytes() for p in written] == [shipped.read_bytes(), deutsch.read_bytes(), francais.read_bytes()]
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in written)
    assert "Exported 3 translation(s)" in info.call_args[0][1]
    assert shipped.exists() and deutsch.exists() and francais.exists()     # exporting copies


def test_export_several_asks_before_replacing(window):
    _shipped, deutsch, francais = more_translations(window)
    window.listbox.selection_set(2, 3)
    out = window.test["tmp"] / "out"
    out.mkdir()
    (out / deutsch.name).write_bytes(b"mine")
    with mock.patch.object(tw.filedialog, "askdirectory", return_value=str(out)), \
            mock.patch.object(tw.messagebox, "askyesno", return_value=False) as ask, \
            mock.patch.object(tw.messagebox, "showinfo"):
        assert window.export() == [out / francais.name]
    assert ask.call_args[1]["default"] == "no" and deutsch.name in ask.call_args[0][1]
    assert (out / deutsch.name).read_bytes() == b"mine"


def test_the_help_explains_selecting_deleting_and_exporting():
    text = " ".join(tw.HELP[1])
    for words in ("Ctrl+click", "Shift+click", "Ctrl+A", "Select All", "Export...", "Delete...", "Recycle Bin",
                  "No does nothing", "comes back with the next patcher update", "back in English"):
        assert words in text, words


# ---------------------------------------------------------------------------------------------- the Recycle Bin


def test_recycle_uses_shfileoperation_with_allow_undo(tmp_path):
    import ctypes
    files = [tmp_path / "a b.txt", tmp_path / "Français.txt"]
    for f in files:
        f.write_bytes(b"x")
    seen = {}

    def operation(pointer):
        op = pointer._obj
        seen["func"], seen["flags"] = op.wFunc, op.fFlags
        size = sum(len(str(f.resolve())) + 1 for f in files) + 1
        seen["from"] = ctypes.wstring_at(op.pFrom, size)
        seen["to"] = op.pTo
        for f in files:
            f.unlink()
        return 0
    tr.recycle(files, operation)
    assert seen["func"] == tr.FO_DELETE == 3
    assert seen["flags"] & tr.FOF_ALLOWUNDO and seen["flags"] & tr.FOF_NOCONFIRMATION
    assert seen["from"] == "\0".join(str(f.resolve()) for f in files) + "\0\0"    # full paths, double-null ended
    assert not seen["to"]
    source = tr.recycle.__code__.co_names
    assert "unlink" not in source and "remove" not in source and "rmtree" not in source   # never a hard delete


@pytest.mark.parametrize("result, aborted, message", [(2, 0, "error 0x2"), (0, 1, "cancelled")])
def test_recycle_reports_a_failure(tmp_path, result, aborted, message):
    path = tmp_path / "t.txt"
    path.write_bytes(b"x")

    def operation(pointer):
        pointer._obj.fAnyOperationsAborted = aborted
        return result
    with pytest.raises(OSError, match=message):
        tr.recycle([path], operation)
    assert path.exists()


def test_recycle_a_missing_file_touches_nothing(tmp_path):
    here = tmp_path / "here.txt"
    here.write_bytes(b"x")
    operation = mock.Mock(return_value=0)
    with pytest.raises(OSError, match="gone.txt"):
        tr.recycle([here, tmp_path / "gone.txt"], operation)
    operation.assert_not_called()
    assert here.exists()