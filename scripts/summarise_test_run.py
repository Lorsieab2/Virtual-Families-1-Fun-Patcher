"""Turn a pytest JUnit XML report into a Markdown summary (the GitHub Actions step summary):
counts per test file, every failure, and every skip reason with how many tests it covers.

    python scripts/summarise_test_run.py junit.xml >> "$GITHUB_STEP_SUMMARY"
"""
from __future__ import annotations

import collections
import sys
import xml.etree.ElementTree as ET


def outcome(case) -> tuple[str, str]:
    for kind in ("failure", "error", "skipped"):
        node = case.find(kind)
        if node is not None:
            return kind, (node.get("message") or "").strip()
    return "passed", ""


def module_path(classname: str) -> str:
    """tests.test_patcher.StubIsCurrent -> tests/test_patcher.py (a test class is not part of the file)."""
    parts = classname.split(".")
    end = next((i for i, part in enumerate(parts) if part.startswith("test_")), len(parts) - 1)
    return "/".join(parts[:end + 1]) + ".py"


def summarise(path: str) -> str:
    root = ET.parse(path).getroot()
    per_file: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    failures, skips = [], collections.Counter()
    for case in root.iter("testcase"):
        file = (case.get("file") or module_path(case.get("classname", "?"))).replace("\\", "/")
        kind, message = outcome(case)
        per_file[file][kind] += 1
        if kind in ("failure", "error"):
            failures.append(f"- `{case.get('classname')}::{case.get('name')}` ({kind}): {message[:200]}")
        elif kind == "skipped":
            skips[message] += 1
    totals = sum(per_file.values(), collections.Counter())
    lines = ["## Test run", "",
             " / ".join(f"**{totals[k]}** {k}" for k in ("passed", "failure", "error", "skipped")), "",
             "| file | passed | failed | errors | skipped |", "|---|---:|---:|---:|---:|"]
    for file in sorted(per_file):
        c = per_file[file]
        lines.append(f"| `{file}` | {c['passed']} | {c['failure']} | {c['error']} | {c['skipped']} |")
    if failures:
        lines += ["", "### Failures", *failures]
    if skips:
        lines += ["", "### Skipped", "", "| tests | reason |", "|---:|---|"]
        lines += [f"| {n} | {reason} |" for reason, n in skips.most_common()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(summarise(sys.argv[1]))
