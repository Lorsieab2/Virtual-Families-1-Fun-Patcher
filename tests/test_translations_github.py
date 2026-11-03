"""Download from GitHub... (patcher/vf1_translations_github.py, the Translations window's DownloadDialog) and the
public folder's README (translations/README.md). GitHub is a stand-in: no request leaves the machine."""
from __future__ import annotations

import json
import tkinter as tk
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

import pytest

from conftest import ROOT

import translation_format as tfmt
import vf1_translations as tr
import vf1_translations_github as gh

BRANCH = "main"
API = gh.API
RAW = gh.RAW + BRANCH + "/translations/"


def translation(language="Français", code="fr", translator="Ann Lee", text="Terminé") -> bytes:
    f = tfmt.new_file("vf1", [tfmt.Entry(tfmt.make_key("strings", "1050", "Done"), "Done")], language, code,
                      translator)
    f.rows[0].translation = text
    return tfmt.to_bytes(f)


class FakeGitHub:
    """The public API's answers for a translations/ folder: name -> (bytes, last-commit date)."""

    def __init__(self, files: dict[str, tuple[bytes, str]], fail: dict[str, Exception] | None = None):
        self.files = files
        self.fail = fail or {}
        self.urls: list[str] = []

    def __call__(self, url, branch=None, limit=1024 * 1024):
        gh.check_url(url, branch)                     # the real allow-list, on every address asked for
        self.urls.append(url)
        for part, exc in self.fail.items():
            if part in url:
                raise exc
        if url == API:
            return json.dumps({"default_branch": BRANCH}).encode()
        if url.startswith(f"{API}/contents/translations?ref="):
            return json.dumps([{"name": n, "type": "file", "sha": gh.git_blob_sha(d), "size": len(d)}
                               for n, (d, _when) in self.files.items()]
                              + [{"name": "README.md", "type": "file", "sha": "0" * 40, "size": 10},
                                 {"name": "sub", "type": "dir", "sha": "1" * 40, "size": 0}]).encode()
        if url.startswith(f"{API}/commits?"):
            name = url.split("path=translations%2F", 1)[1].split("&", 1)[0]
            return json.dumps([{"commit": {"committer": {"date": self.files[name][1]}}}]).encode()
        if url.startswith(RAW):
            return self.files[url[len(RAW):]][0]
        raise AssertionError(url)


@pytest.fixture
def files():
    return {
        "fr.tsv": (translation(), "2026-11-01T10:00:00Z"),
        "fr-zoe.tsv": (translation(translator="Zoë"), "2026-11-02T08:30:00Z"),
        "de.tsv": (translation("Deutsch", "de", "Bob", "Fertig"), "2026-10-30T12:00:00Z"),
    }


def test_the_list_has_language_credit_date_and_status(tmp_path, files):
    (tmp_path / "vf1").mkdir()
    (tmp_path / "vf1" / "de.tsv").write_bytes(files["de.tsv"][0])                      # installed, the same
    (tmp_path / "vf1" / "fr.tsv").write_bytes(translation(text="Fini"))                # installed, different
    remotes = gh.list_remote(tmp_path, FakeGitHub(files))
    by = {r.name: r for r in remotes}
    assert set(by) == {"fr.tsv", "fr-zoe.tsv", "de.tsv"}                              # no README, no folder
    assert (by["fr.tsv"].language, by["fr.tsv"].code, by["fr.tsv"].translator) == ("Français", "fr", "Ann Lee")
    assert by["fr-zoe.tsv"].changed == "2026-11-02" and by["de.tsv"].changed == "2026-10-30"   # commits API, path=
    assert by["de.tsv"].status == gh.INSTALLED
    assert by["fr.tsv"].status == gh.UPDATE                                            # contents sha != local blob
    assert by["fr-zoe.tsv"].status == gh.NOT_INSTALLED
    labels = dict(zip((r.name for r in remotes), gh.labels(remotes)))
    assert labels["fr.tsv"] == "Français (by Ann Lee)" and labels["fr-zoe.tsv"] == "Français (by Zoë)"
    assert labels["de.tsv"] == "Deutsch"                                              # one file: no credit needed


def test_only_the_default_branch_is_offered(tmp_path, files):
    fake = FakeGitHub(files)
    gh.list_remote(tmp_path, fake)
    assert f"{API}/contents/translations?ref={BRANCH}" in fake.urls
    assert all(f"/{BRANCH}/translations/" in u for u in fake.urls if "raw.githubusercontent.com" in u)
    assert all("sha=main" in u for u in fake.urls if "/commits?" in u)


def test_the_git_blob_sha_is_githubs():
    assert gh.git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"   # git hash-object


def test_installing_validates_as_data_first(tmp_path, files):
    files = dict(files)
    files["xx.tsv"] = (b"Key\tEnglish\nnot a translation", "2026-11-01T00:00:00Z")
    files["em.tsv"] = (translation(text="Écrivez à someone@example.com"), "2026-11-01T00:00:00Z")
    remotes = gh.list_remote(tmp_path, FakeGitHub(files))
    by = {r.name: r for r in remotes}
    assert by["xx.tsv"].problem.startswith("cannot be used") and "mail" in by["em.tsv"].problem
    results = gh.install(list(by.values()), tmp_path, FakeGitHub(files))
    ok = {r.name for r, path, _p in results if path is not None}
    assert ok == {"fr.tsv", "fr-zoe.tsv", "de.tsv"}
    assert sorted(p.name for p in (tmp_path / "vf1").iterdir()) == ["de.tsv", "fr-zoe.tsv", "fr.tsv"]
    tampered = by["fr.tsv"]
    tampered.data = translation(text="Changé")                                          # not the listed blob
    (_r, path, problem), = gh.install([tampered], tmp_path / "other", FakeGitHub(files))
    assert path is None and "did not match" in problem
    big = gh.Remote("big.tsv", "0" * 40, 0, RAW + "big.tsv", BRANCH, data=b"x" * (gh.MAX_FILE + 1))
    assert "too large" in gh.install([big], tmp_path)[0][2]
    # what was installed shows in the Translations window's list, from GitHub
    names = {i.path.name: i for i in tr.installed("vf1", tmp_path)}
    assert {"fr.tsv", "fr-zoe.tsv", "de.tsv"} <= set(names) and names["de.tsv"].shipped


def test_no_network_and_the_rate_limit_are_told_plainly(tmp_path, files):
    offline = FakeGitHub(files, {"api.github.com/repos": gh.GitHubError(
        "Could not reach GitHub. Please check your internet connection and try again.")})
    with pytest.raises(gh.GitHubError, match="internet connection"):
        gh.list_remote(tmp_path, offline)

    def raising(exc):
        def opener_open(self, request, timeout=None):
            raise exc
        return opener_open
    with mock.patch("urllib.request.OpenerDirector.open", raising(urllib.error.URLError("no route"))):
        with pytest.raises(gh.GitHubError, match="internet connection"):
            gh.fetch(API)
    headers = Message()
    headers["x-ratelimit-remaining"] = "0"
    headers["x-ratelimit-reset"] = "1893456000"
    limited = urllib.error.HTTPError(API, 403, "rate limit", headers, None)
    with mock.patch("urllib.request.OpenerDirector.open", raising(limited)):
        with pytest.raises(gh.GitHubError, match="limit"):
            gh.fetch(API)
    with mock.patch("urllib.request.OpenerDirector.open", raising(urllib.error.HTTPError(API, 429, "x", Message(), None))):
        with pytest.raises(gh.GitHubError, match="limit"):
            gh.fetch(API)
    assert not (tmp_path / "vf1").exists()                                              # nothing changed


def test_only_this_repositorys_translations_folder_on_two_hosts():
    gh.check_url(API)
    gh.check_url(f"{API}/contents/translations?ref=main")
    gh.check_url(f"{API}/commits?path=translations%2Ffr.tsv&sha=main&per_page=1")
    gh.check_url(RAW + "fr.tsv", BRANCH)
    for bad, branch in [
        ("http://api.github.com/repos/Lorsieab2/Virtual-Families-1-Fun-Patcher", None),       # not https
        ("https://example.com/repos/Lorsieab2/Virtual-Families-1-Fun-Patcher", None),         # another host
        ("https://api.github.com/repos/someone/else", None),                                  # another repository
        (f"{API}/contents/patcher/vf1_patcher.py", None),                                     # another folder
        (f"{API}/issues", None),
        (gh.RAW + "main/patcher/vf1fun.dll", BRANCH),
        (gh.RAW + "other-branch/translations/fr.tsv", BRANCH),                                # not the default
        (RAW + "../patcher/x.tsv", BRANCH),
        ("https://user:pw@api.github.com/repos/Lorsieab2/Virtual-Families-1-Fun-Patcher", None),
        ("https://raw.githubusercontent.com.evil.example/Lorsieab2/Virtual-Families-1-Fun-Patcher/main/translations/x",
         BRANCH),
    ]:
        with pytest.raises(gh.GitHubError):
            gh.check_url(bad, branch)
    with pytest.raises(gh.GitHubError):                                                 # a redirect elsewhere
        gh._Redirects(BRANCH).redirect_request(None, None, 302, "", {}, "https://example.com/x.tsv")


def test_no_credentials_and_nothing_about_the_player_is_sent(monkeypatch):
    seen = {}

    def opener_open(self, request, timeout=None):
        seen.update({k.lower(): v for k, v in request.header_items()})
        seen["url"] = request.full_url
        seen["data"] = request.data

        class Reply:
            def read(self, n):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Reply()
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    with mock.patch("urllib.request.OpenerDirector.open", opener_open):
        gh.fetch(API)
    assert set(seen) <= {"user-agent", "accept", "url", "data"}
    assert seen["data"] is None and "secret-token" not in json.dumps(seen)
    source = (ROOT / "patcher" / "vf1_translations_github.py").read_text(encoding="utf-8")
    for word in ("Authorization", "environ", "getenv", "token", "cookie", "netrc", "keyring", "getpass"):
        assert word.lower() not in source.lower(), word


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


def test_the_dialog_lists_and_downloads_several_at_once(root, tmp_path, files):
    import vf1_translations_window as tw
    done = []
    dialog = tw.DownloadDialog(root, tmp_path, on_installed=lambda: done.append(1), http=FakeGitHub(files),
                               background=False)
    rows = [dialog.tree.item(i, "values") for i in dialog.tree.get_children()]
    assert [r[0] for r in rows] == ["Français (by Ann Lee)", "Français (by Zoë)", "Deutsch"]
    assert rows[0][1] == "Ann Lee" and rows[0][2] == "2026-11-01" and rows[0][3] == gh.NOT_INSTALLED
    assert str(dialog.tree.cget("selectmode")) == "extended"
    dialog.tree.selection_set(("0", "2"))                                                 # multi-select
    got = dialog.download()
    assert sorted(r.name for r in got) == ["de.tsv", "fr.tsv"] and done == [1]
    assert sorted(p.name for p in (tmp_path / "vf1").iterdir()) == ["de.tsv", "fr.tsv"]
    rows = [dialog.tree.item(i, "values") for i in dialog.tree.get_children()]
    assert [r[3] for r in rows] == [gh.INSTALLED, gh.NOT_INSTALLED, gh.INSTALLED]
    dialog.select_all()
    assert len(dialog.selected()) == 3
    dialog.window.destroy()


def test_the_dialog_says_when_github_cannot_be_reached(root, tmp_path, files):
    import vf1_translations_window as tw
    offline = FakeGitHub(files, {"api.github.com": gh.GitHubError(
        "Could not reach GitHub. Please check your internet connection and try again.")})
    dialog = tw.DownloadDialog(root, tmp_path, http=offline, background=False)
    assert dialog.tree.get_children() == () and "internet connection" in dialog.status.get()
    assert dialog.download() == [] and not (tmp_path / "vf1").exists()
    dialog.window.destroy()


def test_the_window_has_the_button_and_the_delete_prompt_says_download_again(root, tmp_path):
    import vf1_translations_window as tw
    window = tw.TranslationsWindow(root, "vf1", {"vf1": []}, folder=tmp_path, choices_path=tmp_path / "c.json")
    texts = []

    def walk(w):
        for child in w.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                pass
            walk(child)
    walk(window.window)
    assert "Download from GitHub..." in texts
    (tmp_path / "vf1").mkdir()
    (tmp_path / "vf1" / "fr.tsv").write_bytes(translation())
    window.refresh()
    prompt = window.delete_prompt(window.items, False, None)
    assert "comes back with the next patcher update" in prompt
    assert "downloaded again with Download from GitHub" in prompt
    window.close()


# ---------------------------------------------------------------------------------------------- the README


def test_the_public_folders_readme_has_the_share_dialogs_exact_sentences():
    readme = (ROOT / "translations" / "README.md").read_text(encoding="utf-8")
    for sentence in ("Please DO NOT put ANY PRIVATE DETAILS YOU DO NOT WANT TO MAKE PUBLIC!",
                     "Email addresses are never saved and are rejected from translation files."):
        assert sentence in tr.SHARE_CONFIRMATION                                         # the code's own constant
        assert sentence in readme
    assert tfmt.EMAIL_MESSAGE in readme
    for words in ("Add file", "Upload files", "pull request", "@translator", "credit name", "VirusTotal",
                  "partners", "Make a translation", "Download from GitHub...", "https://github.com/signup"):
        assert words in readme, words
