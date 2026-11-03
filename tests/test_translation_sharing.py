"""Sharing translations on GitHub: the owner's exact Share on GitHub... wording (No is the default and does
nothing), the credit name typed by hand and never filled in, email refusal everywhere, the issue form, the
"accept-translation" Action (minimal permissions, no issue field ever in a shell command, the bot's identity, the
size limit) and scripts/accept_translation.py (the issue read as data, the file checked as data only, only the
typed credit name added, problems commented).  Ported from the Fish and Plant Tycoon Fix Patcher."""
from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import accept_translation as at  # noqa: E402
import translation_format as tfmt  # noqa: E402
import vf1_translations as tr  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "accept-translation.yml"
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "translation.yml"
URL = "https://github.com/user-attachments/files/123456/Virtual.Families.-.Francais.txt"

# The owner's words, exactly (2026-11-02).
OWNER_TEXT = (
    "This button allows you to share your game translation to the patcher's Public Github. IF ACCEPTED, everyone "
    "who uses this patcher will be able to see your translation in the game and your username will be included in "
    "the credits. Please DO NOT put ANY PRIVATE DETAILS YOU DO NOT WANT TO MAKE PUBLIC!\n\n"
    "Email addresses are never saved and are rejected from translation files.\n\n"
    "This feature is meant to be a community collaboration tool for game modding only.\n\n"
    "You will need a Github account to proceed. Continue?"
)


def translation(translator: str = "", text: str = "Terminé") -> bytes:
    entries = [tfmt.Entry(tfmt.make_key("strings", "1050", "Done"), "Done")]
    f = tfmt.new_file("vf1", entries, "Français", "fr", translator)
    f.rows[0].translation = text
    return tfmt.to_bytes(f)


def body(game="Virtual Families", language="Français", credit="Ann Lee", licence="- [X] I made this translation",
         file=f"[Virtual Families - Français.txt]({URL})") -> str:
    return (f"### Game\n\n{game}\n\n### Language\n\n{language}\n\n### Credit name\n\n{credit}\n\n### Coverage\n\n"
            f"_No response_\n\n### Translation file\n\n{file}\n\n### Licence\n\n{licence}\n")


# ---------------------------------------------------------------------------------------------- the dialog text


def test_the_share_dialog_text_is_exactly_the_owners():
    assert tr.SHARE_CONFIRMATION == OWNER_TEXT


def test_share_asks_first_with_no_as_the_default_and_no_does_nothing():
    """The window's share(): askyesno with the owner's text, default "no"; answering No returns before anything
    (no credit dialog, no file, no browser)."""
    source = (ROOT / "patcher" / "vf1_translations_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    share = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "share")
    first = share.body[1] if isinstance(share.body[0], ast.Expr) else share.body[0]
    assert isinstance(first, ast.If)
    call = first.test.operand
    assert ast.unparse(call.func) == "messagebox.askyesno"
    assert ast.unparse(call.args[1]) == "tr.SHARE_CONFIRMATION"
    assert {k.arg: ast.unparse(k.value) for k in call.keywords}["default"] == "'no'"
    assert [ast.unparse(s) for s in first.body] == ["return None"]


# ---------------------------------------------------------------------------------------------- the credit name


def test_the_credit_name_is_typed_and_never_an_email():
    assert tr.check_credit_name("  Ann   Lee ") == "Ann Lee"
    for bad in ("", "   ", "ann@example.com", "ann [at] example [dot] com", "ann＠example.com", "a" * 61):
        with pytest.raises(tr.TranslationProblem):
            tr.check_credit_name(bad)


def test_the_credit_dialog_starts_empty_and_nothing_reads_an_identity():
    source = (ROOT / "patcher" / "vf1_translations_window.py").read_text(encoding="utf-8")
    assert 'self.var = tk.StringVar(master=win, value="")' in source
    for module in ("vf1_translations_window.py", "vf1_translations.py", "translation_format.py"):
        text = (ROOT / "patcher" / module).read_text(encoding="utf-8")
        for never in ("user.email", "user.name", "USERNAME", "getpass", "git config", "GetUserName", "/user/emails"):
            assert never not in text, (module, never)


def test_no_email_address_anywhere_in_the_feature():
    files = [ROOT / "patcher" / f for f in ("vf1_translations_window.py", "vf1_translations.py",
                                            "translation_format.py", "vf1_translation_strings.py")]
    files += [WORKFLOW, TEMPLATE, ROOT / "scripts" / "accept_translation.py", ROOT / "docs" / "translations.md"]
    files += [ROOT / "patcher" / "vf1_translations_github.py", ROOT / "scripts" / "virustotal_scan.py",
              ROOT / "scripts" / "translation_pr_check.py", ROOT / "translations" / "README.md",
              ROOT / ".github" / "workflows" / "translations-check.yml",
              ROOT / ".github" / "workflows" / "translations-rescan.yml"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", text), path


# ---------------------------------------------------------------------------------------------- email refusal


@pytest.mark.parametrize("text", ["Écrivez à ann@example.com", "ann [at] example [dot] com", "ann＠example.org",
                                  "ann at example dot com"])
def test_a_file_with_an_email_is_refused_naming_its_line(text, tmp_path):
    data = translation(text=text)
    parsed = tfmt.parse_bytes(data, "vf1")
    line = next(n for n, row in enumerate(data.decode("utf-8-sig").splitlines(), 1) if row.startswith("strings/"))
    problems = [p for p in parsed.errors if tfmt.EMAIL_MESSAGE in p.message]
    assert problems and problems[0].line == line
    assert f"Line {line}" in str(problems[0])
    report = tfmt.validate(parsed)
    assert not report.usable
    source = tmp_path / "x.txt"
    source.write_bytes(data)
    with pytest.raises(tr.TranslationProblem, match="email"):
        tr.install_file(source, "vf1", folder=tmp_path / "translations")
    assert not (tmp_path / "translations").exists() or not list((tmp_path / "translations").glob("*.txt"))


def test_an_email_in_the_credit_row_is_refused_too():
    assert not tfmt.validate(tfmt.parse_bytes(translation(translator="x@y.org"), "vf1")).usable


# ---------------------------------------------------------------------------------------------- the Action


def flow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_minimal_permissions():
    """Nothing at the top; the scan reads and comments; only the accepting job writes, after the scan."""
    f = flow()
    assert f["permissions"] == {}
    assert f["jobs"]["scan"]["permissions"] == {"contents": "read", "issues": "write"}
    assert f["jobs"]["accept"]["permissions"] == {"contents": "write", "pull-requests": "write", "issues": "write"}


def test_runs_only_on_the_owners_label():
    f = flow()
    on = f[True] if True in f else f["on"]          # YAML 1.1 reads "on" as True
    assert on == {"issues": {"types": ["labeled"]}}
    condition = f["jobs"]["scan"]["if"]
    assert "github.event.label.name == 'accept-translation'" in condition
    assert "'translation'" in condition
    assert f["jobs"]["accept"]["needs"] == "scan"                   # VirusTotal first, the validator only after


def test_no_issue_field_in_any_shell_command():
    f = flow()
    text = WORKFLOW.read_text(encoding="utf-8")
    for job in f["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")
        assert job["env"]["ISSUE_NUMBER"] == "${{ github.event.issue.number }}"
    for field in ("issue.body", "issue.title", "comment.body", "issue.user"):
        assert field not in text


def test_the_virustotal_key_is_only_a_secret_in_the_scanning_steps_environment():
    f = flow()
    text = WORKFLOW.read_text(encoding="utf-8")
    # Two scanning steps: the attachment, then the file written from it (exactly the bytes committed).
    assert text.count("secrets.VT_API_KEY") == 2
    scan = next(s for s in f["jobs"]["scan"]["steps"] if s.get("id") == "scan")
    final = next(s for s in f["jobs"]["accept"]["steps"] if s.get("id") == "final")
    for step in (scan, final):
        assert step["env"] == {"VT_API_KEY": "${{ secrets.VT_API_KEY }}"}
        assert "VT_API_KEY" not in step["run"]
    assert "$VT_API_KEY" not in text                                          # never echoed or passed on
    assert not re.search(r"(echo|printf|cat)[^\n]*VT_API_KEY", text)
    assert f["jobs"]["accept"]["env"]["EXPECTED_SHA256"] == "${{ needs.scan.outputs.sha256 }}"


def test_checks_as_data_and_commits_as_the_bot():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'python -I scripts/accept_translation.py scan "$GITHUB_EVENT_PATH"' in text
    assert 'python -I scripts/accept_translation.py accept "$GITHUB_EVENT_PATH"' in text
    assert 'git config user.name "github-actions[bot]"' in text
    assert 'git config user.email ""' in text
    assert at.MAX_BYTES == 2 * 1024 * 1024


def test_issue_form():
    yaml = pytest.importorskip("yaml")
    form = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert form["labels"] == ["translation"]
    fields = {item.get("id"): item for item in form["body"] if item.get("id")}
    assert set(fields) == {"game", "language", "credit", "coverage", "file", "licence"}
    for required in ("game", "language", "credit", "file"):
        assert fields[required]["validations"]["required"], required
    assert fields["credit"]["attributes"].get("value") is None                  # never filled in
    assert fields["game"]["attributes"]["options"] == ["Virtual Families"]
    assert tfmt.EMAIL_MESSAGE in TEMPLATE.read_text(encoding="utf-8").replace("\n        ", " ")
    url = tr.issue_url("vf1", "Türkçe")
    assert url.startswith("https://github.com/Lorsieab2/Virtual-Families-1-Fun-Patcher/issues/new?")
    for field in ("game", "language"):
        assert f"&{field}=" in url
    assert "credit" not in url and f"template={TEMPLATE.name}" in url


# ---------------------------------------------------------------------------------------------- accepting


def run_event(text: str, data: bytes = b""):
    work, root = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    fetch = mock.Mock(return_value=data or translation())
    result = at.accept({"issue": {"number": 7, "body": text}}, work, fetch=fetch, root=root)
    target = work / "target.txt"
    return result, work, (root / target.read_text(encoding="utf-8")) if target.exists() else None, root


def test_accepted_with_only_the_typed_credit():
    result, work, path, root = run_event(body(), translation("someone else"))
    assert result == "accepted"
    assert path.parent == root / "translations"                        # the public folder
    assert path.name == "fr.tsv"
    parsed = tfmt.parse_bytes(path.read_bytes(), "vf1")
    assert parsed.translator == "Ann Lee"
    pr = (work / "pr_body.md").read_text(encoding="utf-8")
    assert "Closes #7" in pr and "Coverage" in pr


@pytest.mark.parametrize("name,text,data,why", [
    ("email in file", body(), translation(text="Écrivez à x@y.com"), "email"),
    ("email credit", body(credit="ann@example.com"), b"", "email"),
    ("no credit", body(credit="_No response_"), b"", "credit name is missing"),
    ("licence", body(licence="- [ ] I made this translation"), b"", "licence"),
    ("game", body(game="Virtual Villagers"), b"", "Game"),
    ("not github", body(file="[x.txt](https://evil.example/x.txt)"), b"", "No translation file"),
    ("nothing translated", body(), translation(text=""), "no translated line"),
])
def test_refusals_are_commented(name, text, data, why):
    result, work, path, _root = run_event(text, data)
    assert result == "refused", name
    assert path is None
    comment = (work / "comment.md").read_text(encoding="utf-8")
    assert why in comment, name
    assert "x@y.com" not in comment and "ann@example.com" not in comment


def test_downloads_only_from_github_and_at_most_the_limit():
    with pytest.raises(at.Refused):
        at.download("http://github.com/user-attachments/files/1/a.txt")
    with pytest.raises(at.Refused):
        at.download("https://example.com/a.txt")

    class Reply:
        def __init__(self, size):
            self.size = size

        def read(self, n):
            return b"x" * min(n, self.size)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    with mock.patch("urllib.request.OpenerDirector.open", return_value=Reply(at.MAX_BYTES + 10)):
        with pytest.raises(at.Refused):
            at.download(URL)
    with mock.patch("urllib.request.OpenerDirector.open", return_value=Reply(10)):
        assert at.download(URL) == b"x" * 10


def test_form_fields():
    fields = at.form_fields(body())
    assert fields["game"] == "Virtual Families"
    assert fields["coverage"] == ""
    assert at.attachment_url(fields["translation file"]) == URL


# ---------------------------------------------------------------------------------------------- the public folder


@pytest.mark.parametrize("credit,taken,want", [
    ("Ann Lee", [], "fr.tsv"),                                                   # the language's own name
    ("Ann Lee", ["fr.tsv"], "fr-ann-lee.tsv"),                                   # a collision: the credit
    ("Ann Lee", ["FR.tsv", "fr-ann-lee.tsv"], "fr-ann-lee-2.tsv"),               # a second one: a number
    ("Ann Lee", ["fr.tsv", "fr-ann-lee.tsv", "fr-ann-lee-2.tsv"], "fr-ann-lee-3.tsv"),
    ("Zoë Müller-Łukasz", ["fr.tsv"], "fr-zoe-muller-ukasz.tsv"),                # non-ASCII: ASCII only
    ("日本語の名前", ["fr.tsv"], "fr-translator.tsv"),                              # nothing ASCII at all
    ("A" * 80, ["fr.tsv"], "fr-" + "a" * 40 + ".tsv"),                           # at most 40 letters
])
def test_the_public_file_name_never_overwrites(credit, taken, want):
    assert at.target_name("fr", credit, taken) == want
    slug = at.credit_slug(credit)
    assert re.fullmatch(r"[a-z0-9-]{1,40}", slug) and not slug.startswith("-") and not slug.endswith("-")


def test_a_second_translation_of_a_language_goes_beside_the_first():
    work, root = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    (root / "translations").mkdir()
    (root / "translations" / "fr.tsv").write_bytes(b"already here")
    fetch = mock.Mock(return_value=translation())
    assert at.accept({"issue": {"number": 8, "body": body(credit="Zoë Ann")}}, work, fetch=fetch, root=root) == "accepted"
    assert (work / "target.txt").read_text(encoding="utf-8") == "translations/fr-zoe-ann.tsv"
    assert (root / "translations" / "fr.tsv").read_bytes() == b"already here"
    with pytest.raises(at.Refused):
        at.target_name("../x", "Ann", [])


def test_the_accepted_file_must_be_the_scanned_one():
    data = translation()
    result, work, path, _root = run_event(body(), data)
    assert result == "accepted"
    work, root = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    fetch = mock.Mock(return_value=data)
    good = __import__("hashlib").sha256(data).hexdigest()
    assert at.accept({"issue": {"number": 7, "body": body()}}, work, fetch=fetch, root=root,
                     expected_sha256=good) == "accepted"
    for wrong in ("0" * 64, "", "not a hash"):
        work = Path(tempfile.mkdtemp())
        assert at.accept({"issue": {"number": 7, "body": body()}}, work, fetch=fetch, root=Path(tempfile.mkdtemp()),
                         expected_sha256=wrong) == "refused"
        assert "VirusTotal scanned" in (work / "comment.md").read_text(encoding="utf-8")


class FakeScanner:
    def __init__(self, status="clean", engines=()):
        self.status, self.engines, self.seen = status, list(engines), []

    def scan(self, name, data):
        import virustotal_scan as vt
        self.seen.append(name)
        return vt.Verdict(name, __import__("hashlib").sha256(data).hexdigest(), self.status, self.engines,
                          "VirusTotal could not be reached" if self.status == "not scanned" else "")


def test_the_issue_scan_job_refuses_flagged_and_unscanned_files():
    data = translation()
    work = Path(tempfile.mkdtemp())
    scanner = FakeScanner()
    assert at.scan({"issue": {"number": 7, "body": body()}}, work, fetch=mock.Mock(return_value=data),
                   scanner=scanner) == "clean"
    assert (work / "sha256.txt").read_text(encoding="utf-8") == __import__("hashlib").sha256(data).hexdigest()
    for scanner, why in ((FakeScanner("flagged", ["EngineA (malicious)"]), "EngineA (malicious)"),
                         (FakeScanner("not scanned"), "NOT SCANNED")):
        work = Path(tempfile.mkdtemp())
        assert at.scan({"issue": {"number": 7, "body": body()}}, work, fetch=mock.Mock(return_value=data),
                       scanner=scanner) == "refused"
        assert why in (work / "comment.md").read_text(encoding="utf-8")
        assert not (work / "sha256.txt").exists()
    work = Path(tempfile.mkdtemp())                                              # not UTF-8: never sent
    scanner = FakeScanner()
    assert at.scan({"issue": {"number": 7, "body": body()}}, work, fetch=mock.Mock(return_value=b"\xff\xfe\x00bad"),
                   scanner=scanner) == "refused"
    assert scanner.seen == []
