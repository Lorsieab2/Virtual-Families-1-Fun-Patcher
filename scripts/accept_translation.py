"""Accept a translation shared through a GitHub issue (.github/workflows/accept-translation.yml).

    python -I scripts/accept_translation.py <event.json> <work folder>

Run by the Action when the owner adds the "accept-translation" label. Everything in the issue is
untrusted DATA: the issue form is read from the event JSON file (never through a shell), the
attachment is downloaded only from GitHub's own attachment hosts, at most MAX_BYTES, and it is
only ever parsed as text by patcher/translation_format.py -- nothing in it is executed. Then:

* accepted: the file goes to patcher/translations/vf1/Virtual Families - <language>.txt with its
  @translator row set to the typed credit name (and nothing else personal), and <work>/pr_body.md
  is written; the workflow commits it as github-actions[bot] and opens a pull request;
* refused: <work>/comment.md says why (the validator's report, with line numbers), and the
  workflow posts it on the issue.

Exit code 0 in both cases (2 = the event is not usable at all). <work>/result.txt holds
"accepted" or "refused" and <work>/target.txt the added file's path.

Ported from the Fish and Plant Tycoon Fix Patcher (scripts/accept_translation.py).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patcher"))

import translation_format as tfmt  # noqa: E402

MAX_BYTES = 2 * 1024 * 1024
ALLOWED_HOSTS = ("github.com", "user-images.githubusercontent.com", "objects.githubusercontent.com",
                 "private-user-images.githubusercontent.com")
ATTACHMENT_RE = re.compile(r"https://(?:github\.com/(?:user-attachments/files/\d+/|[\w.-]+/[\w.-]+/files/\d+/)"
                           r"[^\s)\]\"'<>]+)")
GAMES = {title: game for game, title in tfmt.GAME_TITLES.items()}
CREDIT_MAX = 60


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
    txt = [u for u in found if urllib.parse.urlparse(u).path.lower().endswith(".txt")]
    if not txt:
        raise Refused("No translation file (.txt) is attached in the \"Translation file\" field.")
    return txt[0]


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


def accept(event: dict, work: Path, fetch=download, root: Path = ROOT) -> str:
    issue = event.get("issue") or {}
    fields = form_fields(str(issue.get("body") or ""))
    number = int(issue.get("number") or 0)
    try:
        game = GAMES.get(fields.get("game", "").strip())
        if game is None:
            raise Refused("The \"Game\" field must be Virtual Families.")
        if "[x]" not in fields.get("licence", "").lower():
            raise Refused("The licence box is not ticked.")
        name = credit_name(fields.get("credit name", ""))
        data = fetch(attachment_url(fields.get("translation file", "")))
        parsed, report = check(data, game)
        language = parsed.language.strip() or tfmt.normalise_credit(fields.get("language", ""))
        if not language or tfmt.contains_email(language):
            raise Refused("The file has no @language row (the language's own name).")
        parsed.set_info("@translator", "", name)
        target = root / "patcher" / "translations" / game / tfmt.file_name(tfmt.GAME_TITLES[game], language)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(tfmt.to_bytes(parsed))
        recheck = tfmt.parse_bytes(target.read_bytes(), game)
        if recheck.fatal or not tfmt.validate(recheck).usable:
            target.unlink()
            raise Refused("The file changed when it was written; please share it again.")
        (work / "target.txt").write_text(target.relative_to(root).as_posix(), encoding="utf-8")
        (work / "pr_body.md").write_text(
            f"Adds the {tfmt.GAME_TITLES[game]} translation \"{language}\" shared in #{number}, credited to "
            f"{name}.\n\nChecked as data by patcher/translation_format.py:\n\n```\n{report.summary()}\n```\n\n"
            f"Closes #{number}\n", encoding="utf-8")
        (work / "result.txt").write_text("accepted", encoding="utf-8")
        return "accepted"
    except Refused as why:
        (work / "comment.md").write_text(
            "This translation could not be added automatically:\n\n```\n" + str(why).replace("```", "'''")[:6000]
            + "\n```\n\nPlease fix the file in the patcher's Translations window (Check shows the same report) and "
            "share it again. " + tfmt.EMAIL_MESSAGE + "\n", encoding="utf-8")
        (work / "result.txt").write_text("refused", encoding="utf-8")
        return "refused"


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    try:
        event = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 2
    work = Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    print(accept(event, work))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
