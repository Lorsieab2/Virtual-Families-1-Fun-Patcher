"""Accept a translation shared through a GitHub issue (.github/workflows/accept-translation.yml).

    python -I scripts/accept_translation.py scan <event.json> <work folder>
    python -I scripts/accept_translation.py accept <event.json> <work folder>
    python -I scripts/accept_translation.py <event.json> <work folder>          (the same as accept)

Run by the Action when the owner adds the "accept-translation" label. Everything in the issue is
untrusted DATA: the issue form is read from the event JSON file (never through a shell), the
attachment is downloaded only from GitHub's own attachment hosts, at most MAX_BYTES, and it is
only ever parsed as text by patcher/translation_format.py -- nothing in it is executed.

* scan (the workflow's first job): the attachment must be a UTF-8 .txt or .tsv of at most MAX_BYTES,
  and VirusTotal must call it clean (scripts/virustotal_scan.py; flagged, unreachable, a timeout or a
  missing VT_API_KEY all refuse it). Exit 0 with its SHA-256 in <work>/sha256.txt (and the step output
  "sha256"), else exit 1 with <work>/comment.md.
* accept (the second job, only after a clean scan): the attachment is downloaded again and must have
  the scanned SHA-256 (EXPECTED_SHA256); then, checked by the validator, it goes to the public folder
  as translations/<language code>.tsv, or translations/<code>-<credit>.tsv when that language is
  already there (target_name: nothing is ever overwritten), with its @translator row set to the typed
  credit name (and nothing else personal), and <work>/pr_body.md is written; the workflow commits it
  as github-actions[bot] and opens a pull request. Refused: <work>/comment.md says why (the
  validator's report, with line numbers), and the workflow posts it on the issue. Exit code 0 in both
  cases (2 = the event is not usable at all). <work>/result.txt holds "accepted" or "refused" and
  <work>/target.txt the added file's path.

Ported from the Fish and Plant Tycoon Fix Patcher (scripts/accept_translation.py).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))
sys.path.insert(0, str(ROOT / "scripts"))

import translation_format as tfmt  # noqa: E402
import vf1_translation_strings  # noqa: E402,F401 -- registers the lines' printf facts with the validator
import virustotal_scan as vt  # noqa: E402

MAX_BYTES = 2 * 1024 * 1024
ALLOWED_HOSTS = ("github.com", "user-images.githubusercontent.com", "objects.githubusercontent.com",
                 "private-user-images.githubusercontent.com")
ATTACHMENT_RE = re.compile(r"https://(?:github\.com/(?:user-attachments/files/\d+/|[\w.-]+/[\w.-]+/files/\d+/)"
                           r"[^\s)\]\"'<>]+)")
GAMES = {title: game for game, title in tfmt.GAME_TITLES.items()}
CREDIT_MAX = 60
PUBLIC_FOLDER = "translations"          # the repository's public folder (translations/README.md)
SLUG_MAX = 40
CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class Refused(Exception):
    pass


def form_fields(body: str) -> dict[str, str]:
    """An issue form's answers: '### Label' headings and the text under each."""
    fields: dict[str, str] = {}
    current = None
    lines: list[str] = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            if current is not None:
                fields[current] = "\n".join(lines).strip()
            current, lines = heading.group(1).strip().lower(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        fields[current] = "\n".join(lines).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in fields.items()}


def credit_name(text: str) -> str:
    name = tfmt.normalise_credit(text)
    if not name:
        raise Refused("The credit name is missing.")
    if tfmt.contains_email(name) or "@" in name or "＠" in name:
        raise Refused("The credit name looks like an email address. " + tfmt.EMAIL_MESSAGE)
    if len(name) > CREDIT_MAX or any(c in name for c in "<>[]`|\\"):
        raise Refused(f"The credit name must be plain text of at most {CREDIT_MAX} letters.")
    return name


def attachment_url(text: str) -> str:
    found = ATTACHMENT_RE.findall(text or "")
    txt = [u for u in found if urllib.parse.urlparse(u).path.lower().endswith((".txt", ".tsv"))]
    if not txt:
        raise Refused("No translation file (.txt) is attached in the \"Translation file\" field.")
    return txt[0]


def credit_slug(name: str) -> str:
    """The credit name in a file name: ASCII, lower case, only a-z, 0-9 and '-', at most SLUG_MAX letters
    ("Zoë Müller" -> "zoe-muller"; a name with no such letter at all -> "translator")."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:SLUG_MAX].strip("-")
    return slug or "translator"


def target_name(code: str, credit: str, taken) -> str:
    """The file's name in the public folder: "<code>.tsv"; when that language is already there,
    "<code>-<credit slug>.tsv"; when that is taken too, "<code>-<credit slug>-2.tsv", -3... Never an existing
    name (compared without case, as Windows does)."""
    code = (code or "").strip()
    if not CODE_RE.match(code):
        raise Refused(f"The file's @code row ({code or 'missing'}) is not a language code such as fr or pt-BR.")
    used = {str(n).lower() for n in taken}
    name = f"{code}.tsv"
    if name.lower() not in used:
        return name
    base = f"{code}-{credit_slug(credit)}"
    name = f"{base}.tsv"
    n = 2
    while name.lower() in used:
        name = f"{base}-{n}.tsv"
        n += 1
    return name


def download(url: str, limit: int = MAX_BYTES) -> bytes:
    """The attachment's bytes, following redirects only to GitHub's own hosts."""
    class Guard(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlparse(newurl).hostname not in ALLOWED_HOSTS:
                raise Refused("The attachment does not come from GitHub.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if urllib.parse.urlparse(url).hostname not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise Refused("The attachment does not come from GitHub.")
    opener = urllib.request.build_opener(Guard())
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "translation-check"}), timeout=60) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise Refused(f"The file is larger than {limit // 1024} KB; a translation is much smaller.")
    return data


def check(data: bytes, game: str) -> tuple[tfmt.TranslationFile, tfmt.Report]:
    parsed = tfmt.parse_bytes(data, game)
    report = tfmt.validate(parsed)
    if parsed.fatal:
        raise Refused("The file cannot be used: " + parsed.fatal)
    if not report.usable:
        raise Refused("The file has an email address. " + tfmt.EMAIL_MESSAGE + "\n\n" + report.summary())
    if report.translated == 0:
        raise Refused("The file has no translated line.\n\n" + report.summary())
    return parsed, report


def _form(event: dict) -> tuple[dict, int, str, str]:
    issue = event.get("issue") or {}
    fields = form_fields(str(issue.get("body") or ""))
    number = int(issue.get("number") or 0)
    game = GAMES.get(fields.get("game", "").strip())
    if game is None:
        raise Refused("The \"Game\" field must be Virtual Families.")
    if "[x]" not in fields.get("licence", "").lower():
        raise Refused("The licence box is not ticked.")
    name = credit_name(fields.get("credit name", ""))
    return fields, number, game, name


def _refuse(work: Path, why) -> str:
    (work / "comment.md").write_text(
        "This translation could not be added automatically:\n\n```\n" + str(why).replace("```", "'''")[:6000]
        + "\n```\n\nPlease fix the file in the patcher's Translations window (Check shows the same report) and "
        "share it again. " + tfmt.EMAIL_MESSAGE + "\n", encoding="utf-8")
    (work / "result.txt").write_text("refused", encoding="utf-8")
    return "refused"


def scan(event: dict, work: Path, fetch=download, scanner: vt.Scanner | None = None) -> str:
    """The first job: the attachment pre-checked and scanned by VirusTotal, failing closed. "clean" (its SHA-256
    in <work>/sha256.txt) or "refused" (<work>/comment.md)."""
    try:
        fields, _number, _game, _name = _form(event)
        url = attachment_url(fields.get("translation file", ""))
        data = fetch(url)
        verdict = vt.scan_files([(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1], data)],
                                scanner or vt.Scanner(vt.key_from_env()), extensions=(".txt", ".tsv"))[0]
    except Refused as why:
        return _refuse(work, why)
    if not verdict.clean:
        (work / "comment.md").write_text("This translation could not be added automatically:\n\n"
                                         + vt.report([verdict]), encoding="utf-8")
        (work / "result.txt").write_text("refused", encoding="utf-8")
        return "refused"
    (work / "sha256.txt").write_text(verdict.sha256, encoding="utf-8")
    (work / "result.txt").write_text("clean", encoding="utf-8")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"sha256={verdict.sha256}\n")
    return "clean"


def accept(event: dict, work: Path, fetch=download, root: Path = ROOT, expected_sha256: str | None = None) -> str:
    issue = event.get("issue") or {}
    number = int(issue.get("number") or 0)
    try:
        fields, number, game, name = _form(event)
        data = fetch(attachment_url(fields.get("translation file", "")))
        if expected_sha256 is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) \
                    or hashlib.sha256(data).hexdigest() != expected_sha256:
                raise Refused("The file is not the one VirusTotal scanned; please share it again.")
        parsed, report = check(data, game)
        language = parsed.language.strip() or tfmt.normalise_credit(fields.get("language", ""))
        if not language or tfmt.contains_email(language):
            raise Refused("The file has no @language row (the language's own name).")
        parsed.set_info("@translator", "", name)
        folder = root / PUBLIC_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / target_name(parsed.code, name, (p.name for p in folder.iterdir()))
        target.write_bytes(tfmt.to_bytes(parsed))
        recheck = tfmt.parse_bytes(target.read_bytes(), game)
        if recheck.fatal or not tfmt.validate(recheck).usable:
            target.unlink()
            raise Refused("The file changed when it was written; please share it again.")
        (work / "target.txt").write_text(target.relative_to(root).as_posix(), encoding="utf-8")
        (work / "pr_body.md").write_text(
            f"Adds the {tfmt.GAME_TITLES[game]} translation \"{language}\" shared in #{number}, credited to "
            f"{name}, as {target.relative_to(root).as_posix()}.\n\nScanned by VirusTotal (clean) and checked as data "
            f"by patcher/translation_format.py:\n\n```\n{report.summary()}\n```\n\n"
            f"Closes #{number}\n", encoding="utf-8")
        (work / "result.txt").write_text("accepted", encoding="utf-8")
        return "accepted"
    except Refused as why:
        return _refuse(work, why)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv.pop(0) if argv[:1] in (["scan"], ["accept"]) else "accept"
    if len(argv) != 2:
        raise SystemExit(__doc__)
    try:
        event = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 2
    work = Path(argv[1])
    work.mkdir(parents=True, exist_ok=True)
    if mode == "scan":
        result = scan(event, work)
        print(result)
        return 0 if result == "clean" else 1
    expected = os.environ.get("EXPECTED_SHA256")
    print(accept(event, work, expected_sha256=expected.strip() if expected is not None else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
