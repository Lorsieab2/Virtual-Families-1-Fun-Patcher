"""scripts/virustotal_scan.py: every user-submitted translation file goes through VirusTotal, failing closed (the
owner, 2026-11-02: "PLEASE RUN EVERY SINGLE USER-SUBMITTED FILE THROUGH VIRUSTOTAL AND REJECT ANYTHING THAT IS
FLAGGED"). VirusTotal is a stand-in here: no request ever leaves the machine, and every sleep is mocked."""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))

import virustotal_scan as vt  # noqa: E402

KEY = "test-key-0123456789"
DATA = "﻿Key\tEnglish\tTranslation\tNotes\r\n@game\tVirtual Families\t\r\n".encode("utf-8")
SHA = hashlib.sha256(DATA).hexdigest()


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeVT:
    """Answers by (method, path) with a queue of (status, json) replies; records every request."""

    def __init__(self, replies: dict, clock: Clock | None = None, request_time: float = 0.0):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.requests: list[tuple[str, str, dict, bytes | None]] = []
        self.clock = clock
        self.request_time = request_time

    def __call__(self, method, url, headers, body=None, timeout=60):
        assert url.startswith(vt.API + "/")
        path = url[len(vt.API):]
        self.requests.append((method, path, dict(headers), body))
        if self.clock is not None:
            self.clock.now += self.request_time
        key = (method, path.split("?")[0])
        queue = self.replies.get(key) or self.replies.get((method, "*"))
        if not queue:
            raise AssertionError(f"unexpected request {key}")
        status, reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return status, json.dumps(reply).encode("utf-8") if reply is not None else b""


def results(**categories):
    return {engine: {"category": cat, "result": None} for engine, cat in categories.items()}


def scanner(fake, clock=None, **kw):
    clock = clock or Clock()
    return vt.Scanner(KEY, http=fake, sleep=clock.sleep, clock=clock, **kw), clock


def known(res, stats=None):
    return (200, {"data": {"attributes": {"last_analysis_results": res, "last_analysis_stats": stats or {}}}})


def test_a_clean_known_file_is_looked_up_by_its_sha256_only():
    fake = FakeVT({("GET", f"/files/{SHA}"): [known(results(A="harmless", B="undetected"))]})
    s, _clock = scanner(fake)
    verdict = s.scan("translations/fr.tsv", DATA)
    assert verdict.status == "clean" and verdict.clean and verdict.sha256 == SHA
    assert [(m, p) for m, p, _h, _b in fake.requests] == [("GET", f"/files/{SHA}")]
    assert fake.requests[0][2]["x-apikey"] == KEY                         # the key only in VirusTotal's header


def test_a_flagged_file_fails_naming_the_engines():
    fake = FakeVT({("GET", f"/files/{SHA}"): [known(results(A="harmless", Bad="malicious", Odd="suspicious"))]})
    verdict = scanner(fake)[0].scan("translations/fr.tsv", DATA)
    assert verdict.status == "flagged" and not verdict.clean
    assert verdict.engines == ["Bad (malicious)", "Odd (suspicious)"]
    text = vt.report([verdict])
    assert "REFUSED" in text and "Bad (malicious)" in text and "Odd (suspicious)" in text
    assert vt.PARTNERS_NOTE in text
    # flagged by the stats alone (no engine named) still fails
    fake = FakeVT({("GET", f"/files/{SHA}"): [known({"A": {"category": "harmless"}}, {"malicious": 1})]})
    assert scanner(fake)[0].scan("x.tsv", DATA).status == "flagged"


def test_an_unknown_file_is_uploaded_and_its_analysis_polled():
    analysis = "NjY0MjRlOTFjMDIzYTMzZTVlZDE5ZWRkNjBkNjY2ZDU6MTY5OTk5"
    fake = FakeVT({
        ("GET", f"/files/{SHA}"): [(404, {"error": {"code": "NotFoundError"}})],
        ("POST", "/files"): [(200, {"data": {"type": "analysis", "id": analysis}})],
        ("GET", f"/analyses/{analysis}"): [(200, {"data": {"attributes": {"status": "queued"}}}),
                                           (200, {"data": {"attributes": {"status": "in-progress"}}}),
                                           (200, {"data": {"attributes": {"status": "completed",
                                                                          "results": results(A="undetected"),
                                                                          "stats": {"malicious": 0}}}})],
    })
    s, clock = scanner(fake, poll=30)
    verdict = s.scan("translations/fr.tsv", DATA)
    assert verdict.status == "clean"
    assert [(m, p) for m, p, _h, _b in fake.requests] == [
        ("GET", f"/files/{SHA}"), ("POST", "/files"), ("GET", f"/analyses/{analysis}"),
        ("GET", f"/analyses/{analysis}"), ("GET", f"/analyses/{analysis}")]
    upload = fake.requests[1]
    assert upload[2]["content-type"].startswith("multipart/form-data; boundary=") and DATA in upload[3]
    assert b'filename="fr.tsv"' in upload[3]
    assert 30 in clock.slept                                                    # polled, not hammered


def test_an_unknown_file_flagged_after_upload_fails():
    fake = FakeVT({
        ("GET", f"/files/{SHA}"): [(404, None)],
        ("POST", "/files"): [(200, {"data": {"id": "abc"}})],
        ("GET", "/analyses/abc"): [(200, {"data": {"attributes": {"status": "completed",
                                                                  "results": results(Z="malicious")}}})],
    })
    verdict = scanner(fake)[0].scan("x.tsv", DATA)
    assert verdict.status == "flagged" and verdict.engines == ["Z (malicious)"]


def test_an_analysis_that_never_finishes_times_out_as_not_scanned():
    fake = FakeVT({
        ("GET", f"/files/{SHA}"): [(404, None)],
        ("POST", "/files"): [(200, {"data": {"id": "abc"}})],
        ("GET", "/analyses/abc"): [(200, {"data": {"attributes": {"status": "queued"}}})],
    })
    s, clock = scanner(fake, timeout=300, poll=30)
    verdict = s.scan("x.tsv", DATA)
    assert verdict.status == "not scanned" and not verdict.clean
    assert "in time" in verdict.detail
    assert clock.now - 1000 <= 300 + 61                                         # within the overall timeout


def test_a_missing_key_is_not_scanned_and_says_so_clearly():
    fake = FakeVT({})
    for key in (None, "", "   "):
        verdict = vt.Scanner(key, http=fake).scan("x.tsv", DATA)
        assert verdict.status == "not scanned" and verdict.detail == vt.MISSING_KEY
    assert fake.requests == []
    assert "VT_API_KEY" in vt.MISSING_KEY and "missing" in vt.MISSING_KEY
    assert vt.MISSING_KEY in vt.report([verdict])


def test_vt_unreachable_or_refusing_never_passes():
    fake = FakeVT({("GET", "*"): [(0, vt.VTError("VirusTotal could not be reached (URLError)"))]})
    assert scanner(fake)[0].scan("x.tsv", DATA).status == "not scanned"
    for status in (401, 403, 500, 503):
        fake = FakeVT({("GET", f"/files/{SHA}"): [(status, {"error": {}})]})
        verdict = scanner(fake)[0].scan("x.tsv", DATA)
        assert verdict.status == "not scanned", status
    fake = FakeVT({("GET", f"/files/{SHA}"): [(200, {"data": {"attributes": {}}})]})   # no results: not a pass
    assert scanner(fake)[0].scan("x.tsv", DATA).status == "not scanned"
    fake = FakeVT({("GET", f"/files/{SHA}"): [(200, None)]})
    assert scanner(fake)[0].scan("x.tsv", DATA).status == "not scanned"


def test_the_rate_limit_waits_with_the_sleep_mocked():
    """4 requests a minute: the fifth waits for the first to age out; a 429 waits a minute and tries again."""
    clock = Clock()
    limiter = vt.RateLimiter(4, clock, clock.sleep)
    for _ in range(4):
        limiter.wait()
    assert clock.slept == []
    limiter.wait()
    assert len(clock.slept) == 1 and 59 <= clock.slept[0] <= 61
    fake = FakeVT({("GET", f"/files/{SHA}"): [(429, {"error": {"code": "QuotaExceededError"}}),
                                              (429, {"error": {"code": "QuotaExceededError"}}),
                                              known(results(A="harmless"))]})
    s, clock = scanner(fake)
    assert s.scan("x.tsv", DATA).status == "clean"
    assert clock.slept[:2] == [60.0, 120.0]                                     # backing off
    assert len(fake.requests) == 3


def test_many_files_are_spaced_to_four_requests_a_minute():
    fake = FakeVT({("GET", "*"): [known(results(A="harmless"))]})
    clock = Clock()
    s = vt.Scanner(KEY, http=fake, sleep=clock.sleep, clock=clock)
    files = [(f"translations/f{n}.tsv", DATA + bytes([65 + n])) for n in range(9)]
    assert all(v.clean for v in vt.scan_files(files, s))
    assert len(fake.requests) == 9 and len(s.limiter.sent) <= 4
    assert sum(clock.slept) >= 120                                              # 9 requests: two waits of a minute


def test_the_precheck_refuses_before_anything_is_sent():
    fake = FakeVT({})
    s, _clock = scanner(fake)
    big = b"a" * (vt.MAX_BYTES + 1)
    verdicts = vt.scan_files([("translations/a.tsv", big), ("translations/b.tsv", b"\xff\xfe\x00x"),
                              ("translations/c.exe", DATA), ("translations/d.tsv", b"a\x00b")], s)
    assert [v.status for v in verdicts] == ["refused"] * 4
    assert "2 MB" in verdicts[0].detail and "UTF-8" in verdicts[1].detail and ".tsv" in verdicts[2].detail
    assert fake.requests == []
    for bad in ("translations/sub/x.tsv", "translations/x.txt", "x.tsv", "translations/../x.tsv",
                "translations/.hidden.tsv", "translations/x y.tsv", "translations/x.tsv/"):
        assert vt.check_path(bad), bad
    assert vt.check_path("translations/fr.tsv") is None and vt.check_path("translations/pt-BR-ann-2.tsv") is None


def test_the_key_never_appears_in_a_report_or_the_output(monkeypatch, capsys, tmp_path):
    fake = FakeVT({("GET", "*"): [known(results(A="malicious"))]})
    clock = Clock()
    monkeypatch.setenv("VT_API_KEY", KEY)
    monkeypatch.setattr(vt, "urllib_request", fake)
    monkeypatch.setattr(vt.time, "sleep", clock.sleep)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "translations").mkdir()
    (tmp_path / "translations" / "fr.tsv").write_bytes(DATA)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    real = vt.Scanner.__init__

    def init(self, key, http=fake, **kw):
        real(self, key, http=fake, sleep=clock.sleep, clock=clock)
    monkeypatch.setattr(vt.Scanner, "__init__", init)
    assert vt.main(["translations/fr.tsv"]) == 1                                # flagged: fails
    out = capsys.readouterr().out
    assert "FLAGGED" in out and KEY not in out and KEY not in summary.read_text(encoding="utf-8")
    monkeypatch.delenv("VT_API_KEY")
    assert vt.main(["translations/fr.tsv"]) == 1                                # no key: fails, says so
    assert vt.MISSING_KEY in capsys.readouterr().out
