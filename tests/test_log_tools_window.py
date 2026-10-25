"""Check Saves & Logs / Repair Saves & Logs in the window (the Tools tab of vf1_patcher_gui.py).

A fake Documents folder in tmp_path holds a family save with its Family Logs (tests/test_log_tools.py's
writer); message boxes are answered by the test, and no game process is ever looked at.
"""
import tkinter as tk

import pytest

import vf1_log_tools as lt
import vf1_patcher_gui as gui
import vf1_save_backup as sb
from test_log_tools import HISTORY, STAMP, death_record, make_family, snapshot


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
def save(tmp_path):
    folder = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    # Bob has a Death record but is alive (a question); Zed vanished with no record (confirmed wrong).
    make_family(folder, deaths=death_record(1, "Bob", 27, "Male", "Old age", 7, 8), counters=(4, 1),
                members_extra=["member\t9\tZed\t0\t600\t1\t2\t1\t0\t90\t0"],
                history=HISTORY + [STAMP + "Zed (Male, 30) joined the family as a child, adopted, generation 1"])
    return folder


@pytest.fixture
def app(tk_root, tmp_path, save, monkeypatch):
    monkeypatch.setattr(gui, "local_settings_path", lambda base_dir=None: tmp_path / "local.json")
    monkeypatch.setattr(gui, "guess_game_dir", lambda: "")
    monkeypatch.setattr(sb, "documents_folder", lambda: tmp_path / "Documents")
    monkeypatch.setattr(sb, "WindowsProcesses", NoProcesses)
    top = tk.Toplevel(tk_root)
    top.withdraw()
    window = gui.VF1PatcherGUI(top)
    window._open_work_wait = lambda label: None
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


def texts(widget):
    return [w.cget("text") for w in walk(widget) if w.winfo_class() in ("TLabel", "TButton", "TCheckbutton", "Label")]


def toplevels(app):
    return [w for w in walk(app.root) if isinstance(w, tk.Toplevel) and w is not app.root]


def test_the_tools_tab_has_both_log_tools_with_question_marks(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    shown = texts(tools)
    assert "Check Saves & Logs..." in shown and "Repair Saves & Logs..." in shown
    assert {"check_logs", "repair_logs"} <= app.help_keys


def test_check_lists_the_families_and_shows_the_report_without_writing(app, save):
    before = snapshot(save)
    picker = app.check_saves_and_logs()
    assert picker._vf1_slots.get(0) == "Save 1: Hopkins (generation 1)"
    assert picker._vf1_slots.get(1) == "Save 2: (no family)"
    picker._vf1_start()
    report = [w for w in toplevels(app) if hasattr(w, "_vf1_text")][-1]
    body = report._vf1_text.get("1.0", "end")
    assert "WRONG     Zed is gone from the save with no record of how. (repairable)" in body
    assert "ASK       Bob has a Death record but is alive in the save." in body
    assert "1 confirmed wrong" in app.status_var.get()
    assert snapshot(save) == before


def test_repair_is_refused_while_the_game_runs(app, save, monkeypatch):
    before = snapshot(save)
    picker = app.repair_saves_and_logs()
    monkeypatch.setattr(sb, "WindowsProcesses", Running)
    picker._vf1_start()
    assert app.shown[-1][0] == "showerror" and "is running" in app.shown[-1][1][1]
    assert snapshot(save) == before


def checklist(app):
    picker = app.repair_saves_and_logs()
    picker._vf1_start()
    return [w for w in toplevels(app) if hasattr(w, "_vf1_go")][-1]


def test_declining_the_confirmation_changes_nothing(app, save, monkeypatch):
    before = snapshot(save)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    box = checklist(app)
    (repair, var), = box._vf1_ticks
    assert var.get() is True and repair.title.startswith("Add an Unaccounted record for Zed")
    (question, answer), = box._vf1_choices
    assert answer.get() == lt.DONT_KNOW
    box._vf1_go()
    assert len(asked) == 1 and "Add an Unaccounted record for Zed" in asked[0][1]
    assert snapshot(save) == before


def test_repair_makes_the_ticked_changes_and_the_answers(app, save, monkeypatch):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    box = checklist(app)
    (question, answer), = box._vf1_choices
    answer.set(question.options[1])                       # keep Bob's Death record: they were brought back
    box._vf1_go()
    assert not box.winfo_exists()
    assert app.shown[-1][0] == "showinfo" and "Repair 1 is done" in app.shown[-1][1][1]
    assert "Unaccounted 1" in lt.log_path(save, 1, lt.UNACCOUNTED, 1).read_bytes().decode("latin-1")
    assert "Death 1" in lt.log_path(save, 1, lt.DEATHS, 1).read_bytes().decode("latin-1")
    assert lt.load_answers(save, 1)[question.key]["answer"] == question.options[1]
    assert [b.label for b in sb.list_backups(save)] and (save / "Backups").is_dir()
    assert "Repair Saves & Logs: Hopkins (Save 1): Repair 1" in app.log_text.get("1.0", "end")


def test_an_answer_is_listed_and_can_be_cleared(app, save, monkeypatch):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    (q,) = lt.check(save, 1).questions()
    lt.apply(save, 1, set(), answers={q.key: q.options[1]})
    box = checklist(app)
    assert box._vf1_choices == []                          # answered before: not asked again
    assert any("Answered before (not asked again): 1" == t for t in texts(box))
    opener = next(w for w in walk(box) if w.winfo_class() == "TButton" and w.cget("text") == "Answered Questions...")
    opener.invoke()
    listing = [w for w in toplevels(app) if hasattr(w, "_vf1_rows")][-1]
    (key, entry, answer, clear), = listing._vf1_rows
    assert key == q.key and answer.get() == q.options[1]
    clear.set(True)
    listing._vf1_keep()
    assert box._vf1_edits["cleared"] == {q.key}
    for _r, var in box._vf1_ticks:
        var.set(False)
    box._vf1_go()
    assert q.key not in lt.load_answers(save, 1)
    assert [x.key for x in lt.check(save, 1).questions()] == [q.key]


def test_nothing_to_repair_says_so(app, tmp_path, monkeypatch):
    folder = tmp_path / "Documents" / "LDW" / "Virtual Families - Modded"
    import shutil
    shutil.rmtree(folder)
    make_family(folder)
    picker = app.repair_saves_and_logs()
    picker._vf1_start()
    assert app.shown[-1][0] == "showinfo" and "nothing to repair" in app.shown[-1][1][1]
