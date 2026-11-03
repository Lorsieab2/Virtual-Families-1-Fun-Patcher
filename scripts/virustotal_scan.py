"""Scan user-submitted translation files with VirusTotal, failing closed.

    python -I scripts/virustotal_scan.py FILE...                  scan these files
    python -I scripts/virustotal_scan.py --changed-since <sha>    scan the translations/ files changed since a commit

The owner (2026-11-02): "MORE SAFETY CHECKS FOR USER SUBMISSIONS: PLEASE RUN EVERY SINGLE USER-SUBMITTED FILE
THROUGH VIRUSTOTAL AND REJECT ANYTHING THAT IS FLAGGED." Used by .github/workflows/translations-check.yml (every
pull request that touches translations/), .github/workflows/accept-translation.yml (a file shared through the
issue form) and .github/workflows/translations-rescan.yml (every push to main under translations/).

* Pre-check (precheck): only a UTF-8 text file (a byte-order mark is fine) of at most MAX_BYTES; a pull request's
  file must be a .tsv directly under translations/ (check_path). Anything else is refused before it is sent.
* Lookup: GET https://www.virustotal.com/api/v3/files/{sha256}. A file VirusTotal does not know yet is uploaded
  (POST /files) and its analysis polled (GET /analyses/{id}) until it completes, within an overall timeout.
* Rate limit: VirusTotal's public API allows 4 requests a minute. Every request waits its turn (RateLimiter);
  a 429 reply waits a minute (then two) and tries again, within the same timeout.
* FAIL CLOSED: any engine that calls the file malicious or suspicious fails it ("flagged", the engines named);
  no key, no answer, an error or the timeout fails it too ("not scanned"). Nothing ever passes by default.
* The key comes only from the VT_API_KEY secret (the environment variable of that name). It is sent only in
  VirusTotal's x-apikey header and never printed, logged or put in a message.

Files sent to VirusTotal can be seen by VirusTotal's partners (security companies); translations/README.md says
so. Nothing here ever executes a submitted file: it is only read as bytes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = "https://www.virustotal.com/api/v3"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15 * 60                 # seconds for one file, upload and analysis included
POLL = 30                         # seconds between two looks at an analysis
PER_MINUTE = 4                    # VirusTotal's public API limit
BAD = ("malicious", "suspicious")
KEY_VARIABLE = "VT_API_KEY"
PATH_RE = re.compile(r"^translations/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.tsv$")

MISSING_KEY = ("NOT SCANNED: the VirusTotal key (the repository secret VT_API_KEY) is missing, so this file could "
               "not be scanned and is not accepted. The owner must add the secret (Settings > Secrets and variables "
               "> Actions > New repository secret, name VT_API_KEY) and run the check again.")
PARTNERS_NOTE = ("Every submitted file is sent to VirusTotal (virustotal.com) to be scanned; VirusTotal's partners "
                 "can see files sent to it.")


@dataclass
class Verdict:
    name: str
    sha256: str
    status: str                                  # "clean", "flagged", "not scanned" or "refused"
    engines: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def clean(self) -> bool:
        return self.status == "clean"

    def line(self) -> str:
        if self.status == "clean":
            return f"{self.name}: clean (VirusTotal, SHA-256 {self.sha256})"
        if self.status == "flagged":
            return (f"{self.name}: FLAGGED by VirusTotal ({len(self.engines)} engine(s): {', '.join(self.engines)}); "
                    f"SHA-256 {self.sha256}. It is refused.")
        if self.status == "refused":
            return f"{self.name}: refused before scanning: {self.detail}"
        return f"{self.name}: NOT SCANNED, so it is refused: {self.detail}"


class VTError(Exception):
    """VirusTotal could not be used (no answer, an error reply)."""


# --------------------------------------------------------------------------- pre-check


def check_path(path: str) -> str | None:
    """Why a pull request's changed path is refused, or None: a .tsv directly under translations/."""
    if not PATH_RE.match(path or "") or ".." in PurePosixPath(path).parts:
        return "only .tsv files directly in the translations/ folder can be submitted (letters, digits, '.', '_', '-')"
    return None


def precheck(name: str, data: bytes, extensions: tuple[str, ...] = (".tsv",)) -> str | None:
    """Why a file is refused before it is sent anywhere, or None: its extension, its size, UTF-8 text."""
    if not name.lower().endswith(extensions):
        return f"only {' or '.join(extensions)} files are accepted"
    if len(data) > MAX_BYTES:
        return f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "the file is not UTF-8 text"
    if "\x00" in text:
        return "the file is not text (it holds NUL bytes)"
    return None


# --------------------------------------------------------------------------- HTTP


def urllib_request(method: str, url: str, headers: dict, body: bytes | None = None,
                   timeout: float = 60) -> tuple[int, bytes]:
    """(status, body) of one HTTPS request to VirusTotal. Network failures raise VTError (without the key)."""
    if not url.startswith(API + "/"):
        raise VTError("refusing a request outside VirusTotal's API")
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:     # noqa: S310 -- fixed https host
            return reply.status, reply.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(64 * 1024) if exc.fp else b""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise VTError(f"VirusTotal could not be reached ({type(reason).__name__})") from None


class RateLimiter:
    """At most `per_minute` requests in any 60 seconds: waits (sleep) for the oldest one to age out."""

    def __init__(self, per_minute: int = PER_MINUTE, clock=time.monotonic, sleep=time.sleep) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self.sleep = sleep
        self.sent: deque[float] = deque()

    def wait(self) -> None:
        now = self.clock()
        while self.sent and now - self.sent[0] >= 60:
            self.sent.popleft()
        if len(self.sent) >= self.per_minute:
            self.sleep(max(0.0, 60 - (now - self.sent[0])) + 0.5)
            self.sent.popleft()
        self.sent.append(self.clock())


# --------------------------------------------------------------------------- scanning


class Scanner:
    def __init__(self, key: str | None, http=urllib_request, sleep=time.sleep, clock=time.monotonic,
                 timeout: float = TIMEOUT, poll: float = POLL) -> None:
        self.key = (key or "").strip()
        self.http = http
        self.sleep = sleep
        self.clock = clock
        self.timeout = timeout
        self.poll = poll
        self.limiter = RateLimiter(PER_MINUTE, clock, sleep)

    def _call(self, method: str, path: str, deadline: float, body: bytes | None = None,
              content_type: str | None = None) -> tuple[int, dict]:
        """One request, waiting its turn; a 429 waits and tries again until the deadline."""
        backoff = 60.0
        while True:
            if self.clock() > deadline:
                raise VTError("VirusTotal did not finish in time")
            self.limiter.wait()
            headers = {"x-apikey": self.key, "accept": "application/json", "user-agent": "translation-scan"}
            if content_type:
                headers["content-type"] = content_type
            status, raw = self.http(method, API + path, headers, body)
            if status == 429:
                self.sleep(backoff)
                backoff = min(backoff * 2, 240.0)
                continue
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, ValueError):
                data = {}
            return status, data if isinstance(data, dict) else {}

    @staticmethod
    def _engines(results) -> list[str]:
        if not isinstance(results, dict):
            return []
        flagged = []
        for engine, result in sorted(results.items()):
            category = (result or {}).get("category") if isinstance(result, dict) else None
            if category in BAD:
                flagged.append(f"{engine} ({category})")
        return flagged

    @staticmethod
    def _stats_bad(stats) -> int:
        if not isinstance(stats, dict):
            return 0
        return sum(int(stats.get(k) or 0) for k in BAD)

    def scan(self, name: str, data: bytes) -> Verdict:
        digest = hashlib.sha256(data).hexdigest()
        if not self.key:
            return Verdict(name, digest, "not scanned", detail=MISSING_KEY)
        deadline = self.clock() + self.timeout
        try:
            status, reply = self._call("GET", f"/files/{digest}", deadline)
            if status == 200:
                attributes = (reply.get("data") or {}).get("attributes") or {}
                return self._verdict(name, digest, attributes.get("last_analysis_results"),
                                     attributes.get("last_analysis_stats"))
            if status in (401, 403):
                return Verdict(name, digest, "not scanned", detail="VirusTotal refused the key (check the VT_API_KEY secret)")
            if status != 404:
                return Verdict(name, digest, "not scanned", detail=f"VirusTotal answered {status} to the lookup")
            boundary = uuid.uuid4().hex
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", name.rsplit("/", 1)[-1])[:100] or "translation.tsv"
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe}\"\r\n"
                    f"Content-Type: text/plain\r\n\r\n").encode("ascii") + data + f"\r\n--{boundary}--\r\n".encode("ascii")
            status, reply = self._call("POST", "/files", deadline, body, f"multipart/form-data; boundary={boundary}")
            analysis = (reply.get("data") or {}).get("id") if status == 200 else None
            if not analysis or not re.fullmatch(r"[A-Za-z0-9=_:-]{1,200}", str(analysis)):
                return Verdict(name, digest, "not scanned", detail=f"VirusTotal did not take the upload ({status})")
            while True:
                status, reply = self._call("GET", f"/analyses/{analysis}", deadline)
                if status != 200:
                    return Verdict(name, digest, "not scanned", detail=f"VirusTotal answered {status} to the analysis")
                attributes = (reply.get("data") or {}).get("attributes") or {}
                if attributes.get("status") == "completed":
                    return self._verdict(name, digest, attributes.get("results"), attributes.get("stats"))
                if self.clock() + self.poll > deadline:
                    raise VTError("VirusTotal did not finish the analysis in time")
                self.sleep(self.poll)
        except VTError as exc:
            return Verdict(name, digest, "not scanned", detail=str(exc))
        except Exception as exc:  # noqa: BLE001 -- fail closed on anything unexpected
            return Verdict(name, digest, "not scanned", detail=f"the scan failed ({type(exc).__name__})")

    def _verdict(self, name: str, digest: str, results, stats) -> Verdict:
        engines = self._engines(results)
        if engines or self._stats_bad(stats):
            return Verdict(name, digest, "flagged", engines or ["(engines not named by VirusTotal)"])
        if not isinstance(results, dict) or not results:
            return Verdict(name, digest, "not scanned", detail="VirusTotal has no engine results for it yet")
        return Verdict(name, digest, "clean")


def key_from_env() -> str | None:
    return os.environ.get(KEY_VARIABLE, "").strip() or None


def scan_files(items: list[tuple[str, bytes]], scanner: Scanner | None = None,
               extensions: tuple[str, ...] = (".tsv",)) -> list[Verdict]:
    """Pre-check, then scan, every (name, bytes); a refused file is never sent."""
    scanner = scanner or Scanner(key_from_env())
    out = []
    for name, data in items:
        problem = precheck(name, data, extensions)
        if problem:
            out.append(Verdict(name, hashlib.sha256(data).hexdigest(), "refused", detail=problem))
        else:
            out.append(scanner.scan(name, data))
    return out


def report(verdicts: list[Verdict]) -> str:
    """A Markdown report for a comment (no key, no file content)."""
    ok = verdicts and all(v.clean for v in verdicts)
    head = "VirusTotal: every file is clean." if ok else "VirusTotal: REFUSED. Nothing here can be accepted."
    lines = [f"**{head}**", ""] + [f"- {v.line()}" for v in verdicts] + ["", PARTNERS_NOTE]
    if any(v.detail == MISSING_KEY for v in verdicts):
        lines += ["", MISSING_KEY]
    return "\n".join(lines) + "\n"


def changed_since(before: str, root: Path) -> list[str]:
    """The .tsv files under translations/ changed since a commit (all of them for a new branch)."""
    if not re.fullmatch(r"[0-9a-f]{40}", before or "") or set(before) == {"0"}:
        return sorted(p.relative_to(root).as_posix() for p in (root / "translations").glob("*.tsv"))
    out = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AMR", before, "HEAD", "--", "translations/"],
                         cwd=root, capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.splitlines() if p.startswith("translations/") and p.endswith(".tsv"))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()
    if argv[:1] == ["--changed-since"] and len(argv) == 2:
        paths = changed_since(argv[1], root)
    elif argv and not argv[0].startswith("-"):
        paths = argv
    else:
        print(__doc__)
        return 2
    if not key_from_env():
        print(MISSING_KEY)
    scanner = Scanner(key_from_env())
    verdicts = []
    for path in paths:
        problem = check_path(path) if path.startswith("translations/") else None
        if problem:
            verdicts.append(Verdict(path, "", "refused", detail=problem))
            continue
        with open(root / path, "rb") as f:
            data = f.read(MAX_BYTES + 1)
        verdicts += scan_files([(path, data)], scanner)
    text = report(verdicts) if verdicts else "No translation file to scan.\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    return 0 if all(v.clean for v in verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
