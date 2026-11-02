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
    window.listbox.selection_set(0)
    target = window.test["tmp"] / "exported.txt"
    with mock.patch.object(tw.filedialog, "asksaveasfilename", return_value=str(target)):
        assert window.export() == target
    assert target.read_bytes() == window.test["path"].read_bytes()


def test_share_no_does_nothing(window):
    window.listbox.selection_set(0)
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
    window.listbox.selection_set(0)
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
