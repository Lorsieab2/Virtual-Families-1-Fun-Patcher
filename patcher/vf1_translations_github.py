"""Download from GitHub... (the Translations window): the translations in the patcher's own GitHub repository's
public translations/ folder (translations/README.md), listed and downloaded with GitHub's read-only public API.

* Only api.github.com and raw.githubusercontent.com, and only this repository's translations/ folder on its
  default branch (check_url; a redirect anywhere else is refused). No login and no credentials read from
  anywhere, nothing about the player sent: the requests carry only a fixed User-Agent.
* The list: each .tsv (or .txt) file with its language, its credit (the @translator row), the date it last changed
  (the commits API with path=) and whether it is installed, installed but different ("Update available": the
  contents API's git blob SHA against the installed file's), or not installed.
* Installing: each file is checked as DATA (at most MAX_FILE bytes, its git blob SHA must be the listed one, read
  by translation_format; a file it cannot use or one with an email address is refused) before it is written into
  the patcher's translations\\vf1 folder under its GitHub name. Nothing in it is ever run. A file already there
  under that name is replaced only by its own update (the same language, @code and @translator; the old one goes
  to the Recycle Bin, never a plain delete); anyone else's is kept and the download gets a name of its own
  (kept_name, checked against every name in the folders).
* No network, a timeout or GitHub's hourly limit for anonymous use (60 requests): GitHubError with a message for
  the player; nothing is changed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import unicodedata
import urllib.request
from datetime import datetime, timezone

import translation_format as tfmt
import vf1_translation_strings  # noqa: F401 -- registers the lines' printf facts with the validator
import vf1_translations as tr

OWNER_REPO = "Lorsieab2/Virtual-Families-1-Fun-Patcher"
API = f"https://api.github.com/repos/{OWNER_REPO}"
RAW = f"https://raw.githubusercontent.com/{OWNER_REPO}/"
FOLDER = "translations"
ALLOWED_HOSTS = ("api.github.com", "raw.githubusercontent.com")
MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 200
USER_AGENT = "Virtual-Families-1-Fun-Patcher-translations"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.(tsv|txt)$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")

NOT_INSTALLED = "Not installed"
INSTALLED = "Installed"
UPDATE = "Update available"


class GitHubError(Exception):
    """Something the player must hear about (shown as is)."""


def check_url(url: str, branch: str | None = None) -> None:
    """Refuse any address but this repository's API and its translations/ folder's raw files."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.port not in (None, 443) \
            or parts.username or parts.password:
        raise GitHubError("The patcher only downloads translations from its own GitHub page.")
    path = urllib.parse.unquote(parts.path)
    if ".." in path.split("/"):
        raise GitHubError("The patcher only downloads translations from its own GitHub page.")
    if parts.hostname == "api.github.com":
        if not (path == f"/repos/{OWNER_REPO}" or path.startswith(f"/repos/{OWNER_REPO}/contents/{FOLDER}")
                or path == f"/repos/{OWNER_REPO}/commits"):
            raise GitHubError("The patcher only reads its own GitHub page's translations folder.")
    else:
        prefix = f"/{OWNER_REPO}/{branch}/{FOLDER}/" if branch else None
        if prefix is None or not path.startswith(prefix) or "/" in path[len(prefix):]:
            raise GitHubError("The patcher only downloads translations from its own GitHub page.")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, branch: str | None) -> None:
        self.branch = branch

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.branch)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _rate_limit_message(headers) -> str:
    reset = (headers or {}).get("x-ratelimit-reset") or (headers or {}).get("X-RateLimit-Reset")
    when = ""
    try:
        when = datetime.fromtimestamp(int(reset)).strftime(" (after %H:%M)")
    except (TypeError, ValueError, OSError):
        pass
    return ("GitHub's limit for downloads without an account has been reached for this hour. Please try again "
            f"later{when}.")


def fetch(url: str, branch: str | None = None, limit: int = 1024 * 1024, timeout: float = 30) -> bytes:
    """The bytes at an allowed address (check_url), at most `limit` (+1, so a caller can tell). Never sends a
    credential: a fixed User-Agent and GitHub's JSON type only."""
    check_url(url, branch)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(_Redirects(branch))
    try:
        with opener.open(request, timeout=timeout) as reply:
            return reply.read(limit + 1)
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("x-ratelimit-remaining") if exc.headers else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            raise GitHubError(_rate_limit_message(exc.headers)) from None
        if exc.code == 404:
            raise GitHubError("The translations folder was not found on GitHub.") from None
        raise GitHubError(f"GitHub answered with an error ({exc.code}). Please try again later.") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError("Could not reach GitHub. Please check your internet connection and try again.") from None


def git_blob_sha(data: bytes) -> str:
    """The SHA GitHub's contents API gives a file: the git blob hash."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@dataclass
class Remote:
    name: str
    sha: str
    size: int
    url: str
    branch: str
    language: str = ""
    code: str = ""
    translator: str = ""
    changed: str = ""                 # the date its last commit changed it ("2026-11-02"), "" if unknown
    status: str = NOT_INSTALLED
    data: bytes | None = None
    problem: str = ""

    @property
    def label(self) -> str:
        return self.language or Path(self.name).stem


def _json(url: str, http, branch: str | None = None):
    raw = http(url, branch)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GitHubError("GitHub's answer could not be read. Please try again later.") from None


def default_branch(http=fetch) -> str:
    data = _json(API, http)
    branch = str((data or {}).get("default_branch") or "") if isinstance(data, dict) else ""
    if not BRANCH_RE.match(branch) or ".." in branch:
        raise GitHubError("GitHub's answer could not be read. Please try again later.")
    return branch


def last_changed(name: str, branch: str, http=fetch) -> str:
    """The date the file last changed on the branch (commits API, path=), "" if GitHub does not say."""
    query = urllib.parse.urlencode({"path": f"{FOLDER}/{name}", "sha": branch, "per_page": 1})
    data = _json(f"{API}/commits?{query}", http)
    try:
        stamp = data[0]["commit"]["committer"]["date"]
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).strftime("%Y-%m-%d")
    except (KeyError, IndexError, TypeError, ValueError):
        return ""


def installed_copy(name: str, sha: str, folder: Path, game: str = "vf1") -> Path | None:
    """The local file that IS this GitHub file (the same git blob SHA), wherever it was saved: under its own
    name, or under a name of its own when another translator's file already had that name."""
    place = folder / game
    exact = place / name
    try:
        others = sorted(p for p in place.iterdir() if p != exact and NAME_RE.match(p.name))
    except OSError:
        others = []
    for path in [exact, *others]:
        try:
            if path.is_file() and path.stat().st_size <= MAX_FILE and git_blob_sha(path.read_bytes()) == sha:
                return path
        except OSError:
            continue
    return None


def installed_status(name: str, sha: str, folder: Path, game: str = "vf1") -> str:
    if installed_copy(name, sha, folder, game) is not None:
        return INSTALLED
    try:
        return UPDATE if (folder / game / name).is_file() else NOT_INSTALLED
    except OSError:
        return NOT_INSTALLED


def _slug(text: str) -> str:
    """A credit name as a file-name part: ASCII, lower case, [a-z0-9-], at most 40 letters ("translator" when
    nothing ASCII is left)."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:40].strip("-") or "translator"


def kept_name(name: str, translator: str, taken) -> str:
    """The name a download gets when another translator's file already has its GitHub name: "<stem>-<credit
    slug><ext>", then "-2", "-3"... never one in `taken` (every name in the folders, without case)."""
    used = {str(n).casefold() for n in taken}
    stem, ext = Path(name).stem, Path(name).suffix
    base = f"{stem}-{_slug(translator)}"[:90]
    candidate, number = base + ext, 2
    while candidate.casefold() in used:
        candidate = f"{base}-{number}{ext}"
        number += 1
    return candidate


def list_remote(folder: Path | None = None, http=fetch, game: str = "vf1") -> list[Remote]:
    """Every translation file in the repository's translations/ folder on its default branch, with its language,
    credit, last change and installed status. Raises GitHubError (no network, the hourly limit...)."""
    folder = folder or tr.TRANSLATIONS_DIR
    branch = default_branch(http)
    listing = _json(f"{API}/contents/{FOLDER}?ref={urllib.parse.quote(branch, safe='')}", http)
    if not isinstance(listing, list):
        raise GitHubError("GitHub's answer could not be read. Please try again later.")
    out: list[Remote] = []
    for item in listing[:MAX_FILES]:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = str(item.get("name") or "")
        sha = str(item.get("sha") or "")
        if not NAME_RE.match(name) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        size = int(item.get("size") or 0)
        url = RAW + f"{branch}/{FOLDER}/{urllib.parse.quote(name)}"
        remote = Remote(name, sha, size, url, branch)
        if size > MAX_FILE:
            remote.problem = "too large to be a translation"
        else:
            try:
                data = http(url, branch, MAX_FILE)
                remote.data = data
                info = read_remote(name, data, sha, game)
                remote.language, remote.code, remote.translator = info
            except GitHubError as exc:
                if "limit" in str(exc) or "reach" in str(exc):
                    raise
                remote.problem = str(exc)
        try:
            remote.changed = last_changed(name, branch, http)
        except GitHubError as exc:
            if "limit" in str(exc) or "reach" in str(exc):
                raise
        remote.status = installed_status(name, sha, folder, game)
        out.append(remote)
    return out


def read_remote(name: str, data: bytes, sha: str, game: str = "vf1") -> tuple[str, str, str]:
    """(language, code, credit) of a downloaded file, checked as data; GitHubError when it cannot be used."""
    if len(data) > MAX_FILE:
        raise GitHubError("too large to be a translation")
    if git_blob_sha(data) != sha:
        raise GitHubError("the download did not match GitHub's list; please try again")
    parsed = tfmt.parse_bytes(data, game)
    if parsed.fatal:
        raise GitHubError("cannot be used: " + parsed.fatal)
    report = tfmt.validate(parsed)
    if not report.usable:
        raise GitHubError("has an email address. " + tfmt.EMAIL_MESSAGE)
    translator = "" if tfmt.contains_email(parsed.translator) else parsed.translator.strip()
    return parsed.language.strip(), parsed.code.strip(), translator


def labels(remotes: list[Remote]) -> list[str]:
    """Each file's name in the list: its language, with its credit when a language has more than one file."""
    count: dict[str, int] = {}
    for r in remotes:
        count[r.label.casefold()] = count.get(r.label.casefold(), 0) + 1
    return [f"{r.label} (by {r.translator or Path(r.name).stem})" if count[r.label.casefold()] > 1 else r.label
            for r in remotes]


def install(remotes: list[Remote], folder: Path | None = None, http=fetch, game: str = "vf1") \
        -> list[tuple[Remote, Path | None, str]]:
    """Download (if not yet) and install each chosen file, checked as data first: (remote, path or None, problem)."""
    folder = folder or tr.TRANSLATIONS_DIR
    out = []
    for remote in remotes:
        try:
            if not NAME_RE.match(remote.name):
                raise GitHubError("its name is not a translation file's")
            data = remote.data if remote.data is not None else http(remote.url, remote.branch, MAX_FILE)
            language, code, translator = read_remote(remote.name, data, remote.sha, game)
            already = installed_copy(remote.name, remote.sha, folder, game)
            if already is not None:                          # exactly these bytes are installed
                remote.status = INSTALLED
                out.append((remote, already, ""))
                continue
            target = folder / game / remote.name
            replacing = False
            if target.exists():
                # Replaced only by its own update (the same language, @code and @translator; the old one goes to
                # the Recycle Bin). Anyone else's file with that name is kept, and the download gets its own name.
                old = tr.read_info(target, game)
                if old is not None and tr.is_update(old, language, code, translator):
                    replacing = True
                else:
                    target = target.parent / kept_name(remote.name, translator, tr.taken_names(folder))
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".download")
            temp.write_bytes(data)
            try:
                if replacing:
                    tr.recycle([target])                     # never a plain delete
                temp.replace(target)
            except OSError:
                temp.unlink(missing_ok=True)                 # only our own unfinished download
                raise
            remote.status = INSTALLED
            out.append((remote, target, ""))
        except GitHubError as exc:
            out.append((remote, None, str(exc)))
        except OSError as exc:
            out.append((remote, None, f"could not be saved (nothing was replaced): {exc.strerror or exc}"))
    return out
