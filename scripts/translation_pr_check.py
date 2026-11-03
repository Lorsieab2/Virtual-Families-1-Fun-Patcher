"""Check a pull request's translation files (.github/workflows/translations-check.yml).

    python -I scripts/translation_pr_check.py scan <work folder>
    python -I scripts/translation_pr_check.py validate <work folder>

Runs on pull_request_target with the BASE branch checked out: nothing of the pull request is ever checked out or
run. The pull request's changed files are listed through GitHub's API, and only the changed translations/ files
are fetched, through the API, as DATA (at most MAX_BYTES each, never written where anything would run them):

* scan: every changed file must be a UTF-8 .tsv directly in translations/ (translations/README.md only from the
  owner and collaborators), then each one goes to VirusTotal (scripts/virustotal_scan.py), failing closed. The
  file hashes that passed go to the step output "scanned" for the next job; anything flagged, refused or not
  scanned is commented on the pull request and fails the job, so the validator never runs.
* validate: each scanned file is fetched again (its SHA-256 must be the scanned one) and checked with the base
  branch's own validator (patcher/translation_format.py): the format, keys, placeholders and choices, and email
  addresses (refused, naming the line). The result is commented on the pull request.

Everything about the pull request is untrusted: its number and head come from the event file, file names are
checked against a strict pattern before they are used, and no pull request text ever reaches a shell. The token
(GH_TOKEN, the workflow's own GITHUB_TOKEN) is only sent to api.github.com.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
sys.path.insert(0, str(ROOT / "scripts"))

import translation_format as tfmt  # noqa: E402
import vf1_translation_strings  # noqa: E402,F401 -- registers the lines' printf facts with the validator
import virustotal_scan as vt  # noqa: E402

API = "https://api.github.com"
MAX_BYTES = vt.MAX_BYTES
README = "translations/README.md"
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
NAME_RE = re.compile(r"^translations/(?P<code>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)(?:-[a-z0-9-]+)?\.tsv$")


class CheckError(Exception):
    pass


def show(name: str) -> str:
    """A file name as it may appear in a comment: printable, no backticks, at most 120 letters."""
    clean = "".join(c for c in str(name) if c.isprintable() and c not in "`\r\n")[:120]
    return f"`{clean}`"


def github(method: str, url: str, token: str | None, body: dict | None = None, accept: str = "application/vnd.github+json",
           limit: int = 8 * 1024 * 1024) -> tuple[int, bytes]:
    if urllib.parse.urlparse(url).hostname != "api.github.com" or not url.startswith(API + "/"):
        raise CheckError("refusing a request outside api.github.com")
    headers = {"Accept": accept, "User-Agent": "translation-check", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:      # noqa: S310 -- fixed https host
            return reply.status, reply.read(limit + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError) as exc:
        raise CheckError(f"GitHub could not be reached ({type(exc).__name__})") from None


class PullRequest:
    def __init__(self, event: dict, repo: str, token: str | None, api=github) -> None:
        pr = event.get("pull_request") or {}
        self.number = int(pr.get("number") or event.get("number") or 0)
        head = pr.get("head") or {}
        self.head_sha = str(head.get("sha") or "")
        self.head_repo = str((head.get("repo") or {}).get("full_name") or "")
        self.author = str(pr.get("author_association") or "")
        self.repo = repo
        self.token = token
        self.api = api
        if self.number <= 0 or not SHA_RE.match(self.head_sha) or not REPO_RE.match(self.head_repo) \
                or not REPO_RE.match(repo):
            raise CheckError("the pull request event is not usable")

    def changed(self) -> list[dict]:
        files: list[dict] = []
        for page in range(1, 31):
            status, raw = self.api("GET", f"{API}/repos/{self.repo}/pulls/{self.number}/files?per_page=100&page={page}",
                                   self.token)
            if status != 200:
                raise CheckError(f"GitHub answered {status} to the list of changed files")
            batch = json.loads(raw.decode("utf-8"))
            files += [f for f in batch if isinstance(f, dict)]
            if len(batch) < 100:
                break
        return files

    def fetch(self, path: str) -> bytes:
        """A changed file's bytes at the pull request's head, through the API, at most MAX_BYTES (+1 to tell)."""
        quoted = urllib.parse.quote(path, safe="/")
        status, raw = self.api("GET", f"{API}/repos/{self.head_repo}/contents/{quoted}?ref={self.head_sha}", self.token,
                               accept="application/vnd.github.raw", limit=MAX_BYTES)
        if status != 200:
            raise CheckError(f"GitHub answered {status} for {path}")
        return raw[:MAX_BYTES + 1]

    def comment(self, text: str) -> None:
        status, _raw = self.api("POST", f"{API}/repos/{self.repo}/issues/{self.number}/comments", self.token,
                                {"body": text[:60000]})
        if status not in (200, 201):
            print(f"(the comment could not be posted: {status})")


def translation_paths(pr: PullRequest) -> tuple[list[str], list[vt.Verdict]]:
    """The changed translations/ files to scan, and the ones refused by their name alone."""
    paths, refused = [], []
    for item in pr.changed():
        name = str(item.get("filename") or "")
        old = str(item.get("previous_filename") or "")
        if not name.startswith("translations/") and not old.startswith("translations/"):
            continue
        if item.get("status") == "removed":
            continue
        if name == README:
            if pr.author in TRUSTED:
                continue
            refused.append(vt.Verdict(name, "", "refused", detail="only the owner changes translations/README.md"))
            continue
        problem = vt.check_path(name)
        if problem:
            refused.append(vt.Verdict(name, "", "refused", detail=problem))
        else:
            paths.append(name)
    return paths, refused


def write_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def scan(pr: PullRequest, scanner: vt.Scanner) -> tuple[bool, dict, str]:
    paths, verdicts = translation_paths(pr)
    scanned: dict[str, str] = {}
    for path in paths:
        try:
            data = pr.fetch(path)
        except CheckError as exc:
            verdicts.append(vt.Verdict(path, "", "not scanned", detail=str(exc)))
            continue
        verdict = vt.scan_files([(path, data)], scanner)[0]
        verdicts.append(verdict)
        if verdict.clean:
            scanned[path] = verdict.sha256
    ok = all(v.clean for v in verdicts)
    text = vt.report(verdicts) if verdicts else "No translation file to scan.\n"
    return ok, scanned if ok else {}, text


def file_problems(path: str, data: bytes) -> list[str]:
    """The base branch's validator on one file, as data: every problem that refuses it."""
    problems: list[str] = []
    parsed = tfmt.parse_bytes(data, "vf1")
    if parsed.fatal:
        return [f"the file cannot be used: {parsed.fatal}"]
    report = tfmt.validate(parsed)
    for problem in report.errors:
        problems.append(str(problem))
    if not report.usable and not any("mail" in p for p in problems):
        problems.append(tfmt.EMAIL_MESSAGE)
    if report.translated == 0:
        problems.append("the file has no translated line")
    if tfmt.contains_email(parsed.translator):
        problems.append("the @translator row looks like an email address. " + tfmt.EMAIL_MESSAGE)
    match = NAME_RE.match(path)
    code = parsed.code.strip()
    if not match:
        problems.append("the file name must be translations/<language code>.tsv or "
                        "translations/<language code>-<credit>.tsv")
    elif code.lower() != match.group("code").lower() and not path.lower().startswith(f"translations/{code.lower()}-"):
        problems.append(f"the file name must start with its @code row ({code or 'missing'})")
    return problems


def validate(pr: PullRequest, scanned: dict[str, str]) -> tuple[bool, str]:
    lines: list[str] = []
    ok = True
    if not scanned:
        return True, "Translation check: no translation file to validate.\n"
    for path, digest in sorted(scanned.items()):
        if vt.check_path(path) or not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
            return False, "Translation check: the scan results are not usable.\n"
        data = pr.fetch(path)
        if hashlib.sha256(data).hexdigest() != digest:
            ok = False
            lines.append(f"- {show(path)}: it changed after it was scanned; push again to scan it again.")
            continue
        problems = file_problems(path, data)
        if problems:
            ok = False
            lines.append(f"- {show(path)}: REFUSED")
            lines += [f"    - {p.replace('`', chr(39))[:300]}" for p in problems[:40]]
            if len(problems) > 40:
                lines.append(f"    - ... and {len(problems) - 40} more")
        else:
            lines.append(f"- {show(path)}: OK")
    head = "Translation check: every file is valid." if ok else "Translation check: REFUSED."
    return ok, f"**{head}**\n\n" + "\n".join(lines) + "\n\nChecked as data with the base branch's validator " \
                                                        "(patcher/translation_format.py). " + tfmt.EMAIL_MESSAGE + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("scan", "validate"):
        print(__doc__)
        return 2
    work = Path(argv[1])
    work.mkdir(parents=True, exist_ok=True)
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pr = PullRequest(event, os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN"))
    except (KeyError, OSError, ValueError, CheckError) as exc:
        print(f"Not usable: {exc}")
        return 2
    try:
        if argv[0] == "scan":
            ok, scanned, text = scan(pr, vt.Scanner(vt.key_from_env()))
            write_output("scanned", json.dumps(scanned, separators=(",", ":")))
            if not ok:
                pr.comment(text)
        else:
            try:
                scanned = json.loads(os.environ.get("SCANNED") or "{}")
            except ValueError:
                scanned = None
            if not isinstance(scanned, dict):
                ok, text = False, "Translation check: the scan results are not usable.\n"
            else:
                ok, text = validate(pr, {str(k): str(v) for k, v in scanned.items()})
            pr.comment(text)
    except CheckError as exc:
        ok, text = False, f"Translation check: NOT CHECKED ({exc}); nothing is accepted.\n"
        pr.comment(text)
    (work / "result.md").write_text(text, encoding="utf-8")
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
