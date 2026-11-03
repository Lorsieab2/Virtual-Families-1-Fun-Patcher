"""The three translation-safety rules (the VV chat's Codex review, checked here too):

1. A check speaks only for the commit it checked: the workflows cancel stale runs, the scripts ask GitHub for
   the pull request's head again before acting, and the Share on GitHub... flow commits exactly the bytes
   VirusTotal scanned (SHA-256) and re-reads the issue just before pushing.
2. Names: a player's file never takes the name of one that came with the patcher or from GitHub, the Edit...
   copy is the player's own (never the bare shipped name), Download from GitHub... never takes another
   translator's file's place, and a remembered choice is its source plus its name.
3. Adding (or downloading) a translation replaces an installed one only when the language, @code AND
   @translator match; otherwise both are kept. The replaced one goes to the Recycle Bin (mocked here):
   nothing is ever deleted for good.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from unittest import mock

import pytest
import yaml

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import accept_translation as at  # noqa: E402
import translation_format as tfmt  # noqa: E402
import translation_pr_check as pc  # noqa: E402
import vf1_translations as tr  # noqa: E402
import vf1_translations_github as gh  # noqa: E402
import virustotal_scan as vt  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
REPO = "Lorsieab2/Virtual-Families-1-Fun-Patcher"
HEAD = "a" * 40
NEWER = "b" * 40
ENTRIES = [tfmt.Entry(tfmt.make_key("strings", "1050", "Done"), "Done")]


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def translation(language="Français", code="fr", translator="Ann Lee", text="Terminé") -> bytes:
    f = tfmt.new_file("vf1", ENTRIES, language, code, translator)
    f.rows[0].translation = text
    return tfmt.to_bytes(f)


def write(path: Path, **kw) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(translation(**kw))
    return path


class FakeRecycleBin:
    """tr.recycle stand-in: moves the files into a folder of its own (as the Recycle Bin would)."""

    def __init__(self) -> None:
        self.bin = Path(tempfile.mkdtemp())
        self.calls: list[list[Path]] = []

    def __call__(self, paths, operation=None):
        paths = [Path(p).resolve() for p in paths]
        self.calls.append(paths)
        for n, path in enumerate(paths):
            os.rename(path, self.bin / f"{n}-{path.name}")


@pytest.fixture
def no_plain_delete():
    """Every plain delete patched; the test fails if one is called."""
    with mock.patch.object(Path, "unlink") as unlink, mock.patch("os.remove") as remove, \
            mock.patch("os.unlink") as os_unlink, mock.patch("shutil.rmtree") as rmtree:
        yield
        for plain in (unlink, remove, os_unlink, rmtree):
            plain.assert_not_called()


# ---------------------------------------------------------------------------------------------- 1. workflows


def test_the_pr_check_cancels_stale_runs():
    flow = load("translations-check.yml")
    assert flow["concurrency"]["cancel-in-progress"] is True
    assert "github.event.pull_request.number" in flow["concurrency"]["group"]
    on = flow.get(True) or flow["on"]
    assert "labeled" not in on["pull_request_target"]["types"]        # no label can cancel a real check


def test_the_accept_flow_cancels_stale_runs_and_other_labels_never_cancel_it():
    flow = load("accept-translation.yml")
    assert flow["concurrency"]["cancel-in-progress"] is True
    group = flow["concurrency"]["group"]
    assert "github.event.issue.number" in group
    assert "github.event.label.name == 'accept-translation'" in group and "github.run_id" in group


def test_the_accept_flow_commits_exactly_the_scanned_bytes_and_rechecks_before_pushing():
    flow = load("accept-translation.yml")
    steps = flow["jobs"]["accept"]["steps"]
    ids = [s.get("id") for s in steps]
    final = steps[ids.index("final")]
    assert "accept_translation.py scan-written" in final["run"]
    assert final["env"]["VT_API_KEY"] == "${{ secrets.VT_API_KEY }}"
    opening = steps[-1]
    assert ids.index("final") < len(steps) - 1
    assert opening["env"]["FINAL_SHA256"] == "${{ steps.final.outputs.sha256 }}"
    run = opening["run"]
    order = [run.index(part) for part in ('git add -- "$target"', 'git show ":$target" | sha256sum',
                                          '"$staged" != "$FINAL_SHA256"', "git commit",
                                          'gh api "repos/$GITHUB_REPOSITORY/issues/$ISSUE_NUMBER"',
                                          "accept_translation.py recheck", "git push")]
    assert order == sorted(order)
    assert "set -euo pipefail" in run                                 # a failed recheck stops before the push
    for step in steps:
        assert "${{" not in step.get("run", "")


def test_any_automatic_merge_is_pinned_to_the_checked_commit():
    # The owner merges translation pull requests by hand; should a workflow ever merge, it must name the
    # commit that was checked.
    for path in WORKFLOWS.glob("*.yml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "gh pr merge" in line and not line.lstrip().startswith("#"):
                assert "--match-head-commit" in line, path.name


# ---------------------------------------------------------------------------------------------- 1. scripts


class FakeGitHub:
    def __init__(self, files: dict[str, bytes], heads=()):
        self.files = files
        self.heads = list(heads)
        self.comments: list[str] = []
        self.event = {"pull_request": {"number": 12, "author_association": "NONE",
                                       "head": {"sha": HEAD, "repo": {"full_name": "someone/fork"}}}}

    def __call__(self, method, url, token, body=None, accept="", limit=0):
        if url.endswith("/pulls/12"):
            return 200, json.dumps({"head": {"sha": self.heads.pop(0) if self.heads else HEAD}}).encode()
        if "/pulls/12/files" in url:
            return 200, json.dumps([{"filename": n, "status": "added"} for n in self.files]).encode()
        if method == "POST" and url.endswith("/issues/12/comments"):
            self.comments.append(body["body"])
            return 201, b"{}"
        m = re.match(r"https://api\.github\.com/repos/someone/fork/contents/(.+)\?ref=" + HEAD + "$", url)
        if m:                                                          # always the checked commit
            return 200, self.files[m.group(1)]
        raise AssertionError(url)

    def pr(self):
        return pc.PullRequest(self.event, REPO, "token", api=self)


class CleanScanner:
    def scan(self, name, data):
        return vt.Verdict(name, hashlib.sha256(data).hexdigest(), "clean", [], "")


def run_main(monkeypatch, tmp_path, fake, mode, scanned=None):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(fake.event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    if scanned is not None:
        monkeypatch.setenv("SCANNED", json.dumps(scanned))
    real = pc.PullRequest.__init__
    monkeypatch.setattr(pc.PullRequest, "__init__", lambda self, e, r, t, api=fake: real(self, e, r, t, api=fake))
    monkeypatch.setattr(pc.vt, "Scanner", lambda key: CleanScanner())
    return pc.main([mode, str(tmp_path / "w")])


def test_a_scan_whose_head_moved_fails_without_a_comment(monkeypatch, tmp_path):
    fake = FakeGitHub({"translations/fr.tsv": translation()}, heads=[NEWER])
    assert run_main(monkeypatch, tmp_path, fake, "scan") == 1
    assert fake.comments == []
    assert not (tmp_path / "out.txt").exists()                        # nothing handed to the validator


def test_a_validator_whose_head_moved_never_comments(monkeypatch, tmp_path):
    data = translation()
    fake = FakeGitHub({"translations/fr.tsv": data}, heads=[NEWER])
    scanned = {"translations/fr.tsv": hashlib.sha256(data).hexdigest()}
    assert run_main(monkeypatch, tmp_path, fake, "validate", scanned) == 1
    assert fake.comments == []
    assert "changed during the check" in (tmp_path / "w" / "result.md").read_text(encoding="utf-8")


def test_a_validator_whose_head_stayed_comments_naming_the_commit(monkeypatch, tmp_path):
    data = translation()
    fake = FakeGitHub({"translations/fr.tsv": data})
    scanned = {"translations/fr.tsv": hashlib.sha256(data).hexdigest()}
    assert run_main(monkeypatch, tmp_path, fake, "validate", scanned) == 0
    assert len(fake.comments) == 1 and HEAD[:12] in fake.comments[0] and "every file is valid" in fake.comments[0]


def test_scan_rechecks_the_head_after_scanning():
    fake = FakeGitHub({"translations/fr.tsv": translation()}, heads=[NEWER])
    with pytest.raises(pc.HeadMoved):
        pc.scan(fake.pr(), CleanScanner())


def test_scan_written_scans_the_written_file_and_outputs_its_sha256(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    data = translation(translator="Zoë")
    write_to = root / "translations" / "fr.tsv"
    write_to.parent.mkdir(parents=True)
    write_to.write_bytes(data)
    target = tmp_path / "target.txt"
    target.write_text("translations/fr.tsv", encoding="utf-8")
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    seen = []

    class Scanner:
        def scan(self, name, got):
            seen.append((name, got))
            return vt.Verdict(name, hashlib.sha256(got).hexdigest(), "clean", [], "")

    assert at.scan_written(target, tmp_path / "w", Scanner(), root) == "clean"
    assert seen == [("translations/fr.tsv", data)]
    assert out.read_text(encoding="utf-8") == f"sha256={hashlib.sha256(data).hexdigest()}\n"
    for bad in ("../x.tsv", "translations/../x.tsv", "src/x.tsv", "translations/missing.tsv"):
        target.write_text(bad, encoding="utf-8")
        out.unlink(missing_ok=True)
        assert at.scan_written(target, tmp_path / "w", Scanner(), root) == "refused"
        assert not out.exists()


def test_a_flagged_written_file_gives_no_sha256(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    write(root / "translations" / "fr.tsv")
    target = tmp_path / "target.txt"
    target.write_text("translations/fr.tsv", encoding="utf-8")
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    class Flagging:
        def scan(self, name, got):
            return vt.Verdict(name, hashlib.sha256(got).hexdigest(), "flagged", ["Bad (malicious)"], "")

    assert at.scan_written(target, tmp_path / "w", Flagging(), root) == "refused"
    assert not out.exists() and "Bad" in (tmp_path / "w" / "comment.md").read_text(encoding="utf-8")


BODY = ("### Game\n\nVirtual Families\n\n### Credit name\n\nAnn\n\n### Translation file\n\n"
        "[f.tsv](https://github.com/user-attachments/files/1/f.tsv)\n\n### Licence\n\n- [X] mine\n")


def current(body=BODY, labels=("translation", "accept-translation"), state="open") -> dict:
    return {"body": body, "state": state, "labels": [{"name": n} for n in labels]}


def test_the_issue_is_read_again_before_pushing(tmp_path):
    event = {"issue": {"body": BODY}}
    assert at.still_current(event, current()) == ""
    assert "translation file" in at.still_current(event, current(BODY.replace("files/1/", "files/2/")))
    assert "credit name" in at.still_current(event, current(BODY.replace("Ann", "Bob")))
    assert "label" in at.still_current(event, current(labels=("translation",)))
    assert "closed" in at.still_current(event, current(state="closed"))
    (tmp_path / "event.json").write_text(json.dumps(event), encoding="utf-8")
    (tmp_path / "same.json").write_text(json.dumps(current()), encoding="utf-8")
    (tmp_path / "edited.json").write_text(json.dumps(current(BODY.replace("Ann", "Eve"))), encoding="utf-8")
    assert at.main(["recheck", str(tmp_path / "event.json"), str(tmp_path / "same.json")]) == 0
    assert at.main(["recheck", str(tmp_path / "event.json"), str(tmp_path / "edited.json")]) == 1
    assert at.main(["recheck", str(tmp_path / "event.json"), str(tmp_path / "missing.json")]) == 1


# ---------------------------------------------------------------------------------------------- 2. names


def test_taken_names_include_shipped_and_downloaded_files(tmp_path):
    write(tmp_path / "vf1" / "fr.tsv")
    write(tmp_path / "Virtual Families - Español.txt", language="Español", code="es")
    assert tr.taken_names(tmp_path) == {"vf1", "fr.tsv", "virtual families - español.txt"}
    assert tr.free_name("a.txt", {"b.txt"}) == "a.txt"
    assert tr.free_name("A.txt", {"a.txt", "a (2).txt"}) == "A (3).txt"


def test_an_added_file_never_takes_a_shipped_name(tmp_path):
    shipped = write(tmp_path / "vf1" / "Virtual Families - Français.txt", translator="Old")      # older layout
    source = write(tmp_path / "in" / "mine.txt", translator="Ann")
    target, _report = tr.install_file(source, "vf1", ENTRIES, tmp_path)
    assert target == tmp_path / "Virtual Families - Français (2).txt"
    assert tfmt.parse_bytes(shipped.read_bytes()).translator == "Old"


def test_the_edit_copy_is_the_players_own_and_never_the_bare_shipped_name(tmp_path):
    item = tr.read_info(write(tmp_path / "vf1" / "fr.tsv"), "vf1")
    copy = tr.own_copy_path(item, tmp_path)
    assert copy == tmp_path / "Virtual Families - fr (own copy).txt"
    copy.write_bytes(item.path.read_bytes())
    assert tr.own_copy_path(item, tmp_path) == copy                                    # Edit... again reopens it
    assert copy in [i.path for i in tr.installed("vf1", tmp_path) if not i.shipped]    # listed with the player's
    copy.write_bytes(b"not a translation")
    assert tr.own_copy_path(item, tmp_path) == tmp_path / "Virtual Families - fr (own copy) (2).txt"


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk: {exc}")
    r.withdraw()
    yield r
    r.destroy()


def test_the_window_edits_its_own_copy(root, tmp_path):
    import vf1_translations_window as tw
    shipped = write(tmp_path / "vf1" / "fr.tsv")
    window = tw.TranslationsWindow(root, "vf1", {"vf1": []}, folder=tmp_path, choices_path=tmp_path / "c.json")
    window.entries_cache["vf1"] = ENTRIES
    index = next(n for n, i in enumerate(window.items) if i.path == shipped)
    window.listbox.selection_clear(0, "end")
    window.listbox.selection_set(index + 1)                    # row 0 is English (original)
    with mock.patch.object(tw.messagebox, "askyesno", return_value=True), \
            mock.patch.object(window, "open_editor") as open_editor:
        window.edit()
    opened = open_editor.call_args[0][0]
    assert opened == tmp_path / "Virtual Families - fr (own copy).txt"
    assert opened.read_bytes() == shipped.read_bytes()
    window.close()


def test_the_remembered_choice_is_source_and_name(tmp_path):
    shipped = write(tmp_path / "vf1" / "fr.tsv", translator="Ann")
    mine = write(tmp_path / "fr.tsv", translator="Me")                                # the same bare name
    choices = tmp_path / "choice.json"
    tr.apply_choice("vf1", shipped, [], choices, tmp_path)
    assert tr.load_choices(choices)["vf1"] == "vf1/fr.tsv"
    assert tr.chosen_path("vf1", tr.load_choices(choices), tmp_path) == shipped
    tr.apply_choice("vf1", mine, [], choices, tmp_path)
    assert tr.load_choices(choices)["vf1"] == "fr.tsv"
    assert tr.chosen_path("vf1", tr.load_choices(choices), tmp_path) == mine
    outside = write(tmp_path.parent / (tmp_path.name + "-elsewhere") / "fr.tsv")
    assert tr.relative_name(outside, tmp_path) == str(outside.resolve())
    assert tr.chosen_path("vf1", {"vf1": tr.relative_name(outside, tmp_path)}, tmp_path) == outside.resolve()


def remote(data: bytes, name="fr.tsv") -> gh.Remote:
    language, code, translator = gh.read_remote(name, data, gh.git_blob_sha(data))
    return gh.Remote(name, gh.git_blob_sha(data), len(data), "https://example.invalid/unused", "main",
                     language, code, translator, data=data)


def test_a_download_never_takes_another_translators_file(tmp_path):
    old = write(tmp_path / "vf1" / "fr.tsv", translator="Someone")                  # came with an older patcher
    old_bytes = old.read_bytes()
    choices = tmp_path / "c.json"
    tr.apply_choice("vf1", old, [], choices, tmp_path)
    new = remote(translation(translator="Ann Lee"))
    bin_ = FakeRecycleBin()
    with mock.patch.object(tr, "recycle", bin_):
        [(_r, saved, problem)] = gh.install([new], tmp_path, http=None)
    assert problem == "" and saved == tmp_path / "vf1" / "fr-ann-lee.tsv"
    assert old.read_bytes() == old_bytes and bin_.calls == []
    assert gh.installed_status(new.name, new.sha, tmp_path) == gh.INSTALLED
    with mock.patch.object(tr, "recycle", bin_):
        [(_r, again, _p)] = gh.install([new], tmp_path, http=None)
    assert again == saved                                                             # nothing new
    assert tr.chosen_path("vf1", tr.load_choices(choices), tmp_path) == old          # still Someone's
    assert sorted(p.name for p in (tmp_path / "vf1").iterdir()) == ["fr-ann-lee.tsv", "fr.tsv"]


def test_a_downloaded_name_skips_the_players_names_too(tmp_path):
    write(tmp_path / "vf1" / "fr.tsv", translator="Someone")
    write(tmp_path / "fr-ann-lee.tsv", translator="Me")                              # the player's flat folder
    with mock.patch.object(tr, "recycle", FakeRecycleBin()):
        [(_r, saved, _p)] = gh.install([remote(translation(translator="Ann Lee"))], tmp_path, http=None)
    assert saved.name == "fr-ann-lee-2.tsv"


def test_the_same_translators_download_update_recycles_the_old_version(tmp_path, no_plain_delete):
    old = write(tmp_path / "vf1" / "fr.tsv", translator="Ann Lee", text="Vieux")
    old_bytes = old.read_bytes()
    new = translation(translator="Ann Lee", text="Neuf")
    bin_ = FakeRecycleBin()
    with mock.patch.object(tr, "recycle", bin_):
        [(_r, saved, problem)] = gh.install([remote(new)], tmp_path, http=None)
    assert problem == "" and saved == old and saved.read_bytes() == new
    assert bin_.calls == [[old.resolve()]]
    assert [p.read_bytes() for p in bin_.bin.iterdir()] == [old_bytes]


def test_a_failing_recycle_bin_replaces_nothing_on_download(tmp_path):
    old = write(tmp_path / "vf1" / "fr.tsv", translator="Ann Lee", text="Vieux")
    old_bytes = old.read_bytes()
    with mock.patch.object(tr, "recycle", side_effect=OSError("no bin")):
        [(_r, saved, problem)] = gh.install([remote(translation(translator="Ann Lee"))], tmp_path, http=None)
    assert saved is None and "nothing was replaced" in problem
    assert old.read_bytes() == old_bytes
    assert [p.name for p in (tmp_path / "vf1").iterdir()] == ["fr.tsv"]             # no .download left


# ---------------------------------------------------------------------------------------------- 3. adding


@pytest.fixture
def old(tmp_path):
    return write(tmp_path / "Virtual Families - Français.txt", translator="Ann", text="Vieux")


def add(source: Path, folder: Path):
    bin_ = FakeRecycleBin()
    with mock.patch.object(tr, "recycle", bin_), mock.patch.object(Path, "unlink") as unlink, \
            mock.patch("os.remove") as remove, mock.patch("os.unlink") as os_unlink, \
            mock.patch("shutil.rmtree") as rmtree:
        target, _report = tr.install_file(source, "vf1", ENTRIES, folder)
    for plain in (unlink, remove, os_unlink, rmtree):
        plain.assert_not_called()                                   # nothing is ever deleted for good
    return target, bin_


def test_same_language_code_and_translator_is_an_update(tmp_path, old):
    old_bytes = old.read_bytes()
    source = write(tmp_path / "in" / "new.txt", translator=" ann ", text="Neuf")
    target, bin_ = add(source, tmp_path)
    assert target == old and target.read_bytes() == source.read_bytes()
    assert bin_.calls == [[old.resolve()]]                         # the old one: Recycle Bin
    assert [p.read_bytes() for p in bin_.bin.iterdir()] == [old_bytes]


def test_another_translator_keeps_both(tmp_path, old):
    old_bytes = old.read_bytes()
    target, bin_ = add(write(tmp_path / "in" / "new.txt", translator="Zoe", text="Neuf"), tmp_path)
    assert target == tmp_path / "Virtual Families - Français (by Zoe).txt"
    assert old.read_bytes() == old_bytes and bin_.calls == []
    assert len(tr.installed("vf1", tmp_path)) == 2


def test_another_code_keeps_both(tmp_path, old):
    old_bytes = old.read_bytes()
    target, bin_ = add(write(tmp_path / "in" / "new.txt", code="fr-CA", translator="Ann", text="Neuf"), tmp_path)
    assert target != old and old.read_bytes() == old_bytes and bin_.calls == []


def test_uncredited_files_are_nobodys_update(tmp_path):
    old = write(tmp_path / "Virtual Families - Français.txt", translator="", text="Vieux")
    old_bytes = old.read_bytes()
    target, bin_ = add(write(tmp_path / "in" / "new.txt", translator="", text="Neuf"), tmp_path)
    assert target == tmp_path / "Virtual Families - Français (2).txt"
    assert old.read_bytes() == old_bytes and bin_.calls == []


def test_the_same_bytes_again_change_nothing(tmp_path, old):
    (tmp_path / "in").mkdir()
    source = tmp_path / "in" / "same.txt"
    shutil.copyfile(old, source)
    target, bin_ = add(source, tmp_path)
    assert (target, bin_.calls) == (old, [])
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["Virtual Families - Français.txt"]


def test_a_failing_recycle_bin_replaces_nothing(tmp_path, old):
    old_bytes = old.read_bytes()
    source = write(tmp_path / "in" / "new.txt", translator="Ann", text="Neuf")
    with mock.patch.object(tr, "recycle", side_effect=OSError("no bin")), pytest.raises(tr.TranslationProblem):
        tr.install_file(source, "vf1", ENTRIES, tmp_path)
    assert old.read_bytes() == old_bytes
