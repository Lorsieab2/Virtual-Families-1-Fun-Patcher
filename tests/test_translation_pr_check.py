"""The public translations/ folder's pull request check (.github/workflows/translations-check.yml,
scripts/translation_pr_check.py) and the rescan on main (.github/workflows/translations-rescan.yml): the workflow
never checks out or runs the pull request, VirusTotal runs first and fails closed, the base branch's validator then
checks each file as data, and the result is commented. GitHub and VirusTotal are stand-ins: nothing is sent."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import translation_format as tfmt  # noqa: E402
import translation_pr_check as pc  # noqa: E402
import virustotal_scan as vt  # noqa: E402

CHECK = ROOT / ".github" / "workflows" / "translations-check.yml"
RESCAN = ROOT / ".github" / "workflows" / "translations-rescan.yml"
HEAD = "a" * 40


def load(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def on(flow: dict) -> dict:
    return flow[True] if True in flow else flow["on"]          # YAML 1.1 reads "on" as True


# ---------------------------------------------------------------------------------------------- the workflows


def test_the_check_runs_on_pull_request_target_for_translations_only():
    flow = load(CHECK)
    assert on(flow) == {"pull_request_target": {"types": ["opened", "synchronize", "reopened"],
                                                "paths": ["translations/**"]}}
    assert flow["permissions"] == {"contents": "read", "pull-requests": "write", "issues": "write"}
    for job in flow["jobs"].values():
        assert "permissions" not in job                         # never more than the minimal set


def test_the_check_never_checks_out_or_runs_the_pull_request():
    flow = load(CHECK)
    text = CHECK.read_text(encoding="utf-8")
    for name, job in flow["jobs"].items():
        checkouts = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
        assert len(checkouts) == 1, name
        assert checkouts[0]["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
        assert checkouts[0]["with"]["persist-credentials"] is False
        for step in job["steps"]:
            run = step.get("run", "")
            assert "${{" not in run, step.get("name")           # no pull request text ever reaches a shell
            assert run == "" or run.startswith("python -I scripts/translation_pr_check.py ")
    for head in ("pull_request.head", "head.ref", "head.sha", "head_ref", "github.event.pull_request.title",
                 "pull_request.body", "merge_commit_sha", "refs/pull"):
        assert head not in text, head


def test_virustotal_runs_first_and_the_validator_needs_it():
    flow = load(CHECK)
    assert list(flow["jobs"]) == ["scan", "validate"]
    assert flow["jobs"]["validate"]["needs"] == "scan"
    assert "needs" not in flow["jobs"]["scan"]
    scan_step = next(s for s in flow["jobs"]["scan"]["steps"] if s.get("id") == "scan")
    assert scan_step["run"] == 'python -I scripts/translation_pr_check.py scan "$RUNNER_TEMP/check"'
    validate_step = flow["jobs"]["validate"]["steps"][-1]
    assert validate_step["run"] == 'python -I scripts/translation_pr_check.py validate "$RUNNER_TEMP/check"'
    assert validate_step["env"]["SCANNED"] == "${{ needs.scan.outputs.scanned }}"


@pytest.mark.parametrize("path", [CHECK, RESCAN, ROOT / ".github" / "workflows" / "accept-translation.yml"])
def test_the_virustotal_key_is_a_secret_only_in_one_steps_environment_and_never_echoed(path):
    flow = load(path)
    text = path.read_text(encoding="utf-8")
    # accept-translation scans twice: the attachment, then the file written from it (exactly what is committed).
    steps = 2 if path.name == "accept-translation.yml" else 1
    assert text.count("secrets.VT_API_KEY") == steps
    holders = [s for job in flow["jobs"].values() for s in job["steps"] if "VT_API_KEY" in (s.get("env") or {})]
    assert len(holders) == steps and all(h["env"]["VT_API_KEY"] == "${{ secrets.VT_API_KEY }}" for h in holders)
    assert "$VT_API_KEY" not in text and not re.search(r"(echo|printf|cat|set -x)[^\n]*VT_API_KEY", text)
    for job in flow["jobs"].values():
        assert "VT_API_KEY" not in (job.get("env") or {})


def test_the_rescan_runs_on_push_to_main_under_translations():
    flow = load(RESCAN)
    assert on(flow) == {"push": {"branches": ["main"], "paths": ["translations/**"]}}
    assert flow["permissions"] == {"contents": "read"}
    step = flow["jobs"]["scan"]["steps"][-1]
    assert step["run"] == 'python -I scripts/virustotal_scan.py --changed-since "$BEFORE"'
    assert step["env"]["BEFORE"] == "${{ github.event.before }}"


def test_the_scripts_never_run_a_submitted_file():
    for script in ("translation_pr_check.py", "virustotal_scan.py", "accept_translation.py"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        for call in ("exec(", "eval(", "os.system", "shell=True", "importlib", "pickle", "__import__"):
            assert call not in text, (script, call)


# ---------------------------------------------------------------------------------------------- the validator


def good_file(text: str = "Terminé", code: str = "fr", translator: str = "Ann Lee") -> bytes:
    entries = [tfmt.Entry(tfmt.make_key("strings", "1050", "Done"), "Done"),
               tfmt.Entry(tfmt.make_key("strings", "460", "%d of %d"), "%d of %d")]
    f = tfmt.new_file("vf1", entries, "Français", code, translator)
    f.rows[0].translation = text
    f.rows[1].translation = "%d sur %d"
    return tfmt.to_bytes(f)


def test_the_validator_passes_a_good_file():
    assert pc.file_problems("translations/fr.tsv", good_file()) == []
    assert pc.file_problems("translations/fr-ann-lee-2.tsv", good_file()) == []
    assert pc.file_problems("translations/fr.tsv", good_file("50 % de réduction")) == []   # French percent


def test_the_validator_refuses_a_bad_file_naming_the_line():
    bad = good_file().replace("%d sur %d".encode(), "%s sur %d".encode())
    problems = pc.file_problems("translations/fr.tsv", bad)
    assert any(p.startswith("Line ") and "placeholders" in p for p in problems)
    assert pc.file_problems("translations/fr.tsv", b"not a translation")[0].startswith("the file cannot be used")
    assert any("@code" in p for p in pc.file_problems("translations/de.tsv", good_file()))
    assert any("file name" in p for p in pc.file_problems("translations/Francais.tsv", good_file()))
    assert any("no translated line" in p for p in pc.file_problems("translations/fr.tsv", good_file("")
                                                                   .replace("%d sur %d".encode(), b"")))


def test_the_validator_refuses_an_email_naming_its_line():
    data = good_file("Écrivez à someone@example.com")
    problems = pc.file_problems("translations/fr.tsv", data)
    lines = data.decode("utf-8-sig").split("\r\n")
    line = next(n for n, text in enumerate(lines, 1) if "someone@" in text)
    assert any(p.startswith(f"Line {line}:") and "mail" in p.lower() for p in problems), problems


# ---------------------------------------------------------------------------------------------- the pull request


class FakeGitHub:
    def __init__(self, files: dict[str, bytes], listing: list[dict] | None = None, author="CONTRIBUTOR"):
        self.files = files
        self.listing = listing if listing is not None else [{"filename": n, "status": "added"} for n in files]
        self.comments: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.heads: list[str] = []                    # the head each time it is asked again (default: HEAD)
        self.event = {"pull_request": {"number": 12, "author_association": author,
                                       "head": {"sha": HEAD, "repo": {"full_name": "someone/fork"}}}}

    def __call__(self, method, url, token, body=None, accept="", limit=0):
        assert url.startswith("https://api.github.com/")
        self.requests.append((method, url))
        if url.endswith("/pulls/12"):                 # the head, asked again before acting
            return 200, json.dumps({"head": {"sha": self.heads.pop(0) if self.heads else HEAD}}).encode()
        if "/pulls/12/files" in url:
            return 200, json.dumps(self.listing).encode()
        if method == "POST" and url.endswith("/issues/12/comments"):
            self.comments.append(body["body"])
            return 201, b"{}"
        m = re.match(r"https://api\.github\.com/repos/someone/fork/contents/(.+)\?ref=" + HEAD + "$", url)
        if m and accept == "application/vnd.github.raw":
            name = m.group(1)
            return (200, self.files[name]) if name in self.files else (404, b"")
        raise AssertionError(url)

    def pr(self):
        return pc.PullRequest(self.event, "Lorsieab2/Virtual-Families-1-Fun-Patcher", "token", api=self)


class FakeScanner:
    def __init__(self, status="clean"):
        self.status, self.names = status, []

    def scan(self, name, data):
        self.names.append(name)
        return vt.Verdict(name, hashlib.sha256(data).hexdigest(), self.status,
                          ["Bad (malicious)"] if self.status == "flagged" else [], "")


def test_a_good_pull_request_is_scanned_then_validated_and_commented():
    gh = FakeGitHub({"translations/fr.tsv": good_file()})
    ok, scanned, _text = pc.scan(gh.pr(), FakeScanner())
    assert ok and scanned == {"translations/fr.tsv": hashlib.sha256(good_file()).hexdigest()}
    ok, text = pc.validate(gh.pr(), scanned)
    assert ok and "every file is valid" in text and "`translations/fr.tsv`: OK" in text


@pytest.mark.parametrize("status", ["flagged", "not scanned"])
def test_a_flagged_or_unscanned_file_fails_before_the_validator(status):
    gh = FakeGitHub({"translations/fr.tsv": good_file()})
    ok, scanned, text = pc.scan(gh.pr(), FakeScanner(status))
    assert not ok and scanned == {} and "REFUSED" in text
    assert pc.validate(gh.pr(), scanned)[0]                    # nothing reaches the validator


def test_only_tsv_files_in_the_folder_are_fetched():
    files = {"translations/fr.tsv": good_file(), "translations/evil.exe": b"MZ", "translations/sub/x.tsv": b"x",
             "translations/README.md": b"# hi", "src/other.py": b"print()"}
    listing = [{"filename": n, "status": "added"} for n in files] + [{"filename": "translations/old.tsv",
                                                                      "status": "removed"}]
    gh = FakeGitHub(files, listing)
    scanner = FakeScanner()
    ok, _scanned, text = pc.scan(gh.pr(), scanner)
    assert not ok and scanner.names == ["translations/fr.tsv"]
    fetched = [u for m, u in gh.requests if "/contents/" in u]
    assert fetched == [f"https://api.github.com/repos/someone/fork/contents/translations/fr.tsv?ref={HEAD}"]
    assert "evil.exe" in text and "README.md" in text and "old.tsv" not in text
    owner = FakeGitHub({"translations/README.md": b"# hi"}, author="OWNER")      # the owner may edit the README
    ok, scanned, _text = pc.scan(owner.pr(), FakeScanner())
    assert ok and scanned == {}


def test_a_file_changed_after_its_scan_is_refused():
    gh = FakeGitHub({"translations/fr.tsv": good_file()})
    ok, text = pc.validate(gh.pr(), {"translations/fr.tsv": "0" * 64})
    assert not ok and "changed after it was scanned" in text


def test_an_email_in_a_pull_request_is_commented_with_its_line():
    data = good_file("Écrivez à someone@example.com")
    gh = FakeGitHub({"translations/fr.tsv": data})
    ok, text = pc.validate(gh.pr(), {"translations/fr.tsv": hashlib.sha256(data).hexdigest()})
    assert not ok and "REFUSED" in text and re.search(r"Line \d+:", text)
    assert "someone@example.com" not in text


def test_the_event_must_be_usable():
    for event in ({}, {"pull_request": {"number": 1, "head": {"sha": "x", "repo": {"full_name": "a/b"}}}},
                  {"pull_request": {"number": 1, "head": {"sha": HEAD, "repo": {"full_name": "a/b; rm"}}}}):
        with pytest.raises(pc.CheckError):
            pc.PullRequest(event, "Lorsieab2/Virtual-Families-1-Fun-Patcher", None, api=lambda *a, **k: (500, b""))
    with pytest.raises(pc.CheckError):
        pc.github("GET", "https://example.com/repos/x", None)


def test_the_main_entry_comments_and_fails_closed(monkeypatch, tmp_path):
    gh = FakeGitHub({"translations/fr.tsv": good_file()})
    event = tmp_path / "event.json"
    event.write_text(json.dumps(gh.event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REPOSITORY", "Lorsieab2/Virtual-Families-1-Fun-Patcher")
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("VT_API_KEY", raising=False)
    monkeypatch.setattr(pc, "github", gh)
    real = pc.PullRequest.__init__
    monkeypatch.setattr(pc.PullRequest, "__init__", lambda self, e, r, t, api=gh: real(self, e, r, t, api=gh))
    assert pc.main(["scan", str(tmp_path / "w")]) == 1                    # no key: not scanned, refused
    assert "NOT SCANNED" in gh.comments[-1] and vt.MISSING_KEY in gh.comments[-1]
    assert out.read_text(encoding="utf-8").strip() == "scanned={}"
    monkeypatch.setenv("SCANNED", json.dumps({"translations/fr.tsv": hashlib.sha256(good_file()).hexdigest()}))
    assert pc.main(["validate", str(tmp_path / "w")]) == 0
    assert "every file is valid" in gh.comments[-1]
    monkeypatch.setenv("SCANNED", "not json")
    assert pc.main(["validate", str(tmp_path / "w")]) == 1
