"""Run the whole test suite in parallel, as the Virtual Villagers Fun Patcher does: one pytest process per job,
several at a time, every failure re-run on its own.

    python scripts/run_tests_parallel.py [--quick] [--workers N] [--out DIR]

A job is a test file, except that the files in SPLIT (the ones that dominate the run) are cut into several jobs
of whole tests, dealt out round-robin so their slow tests spread over the jobs. Every job gets the source folders
on PYTHONPATH, -p no:cacheprovider and its own SHORT --basetemp under %TEMP% (deep temp paths pass the
260-character limit), and every DLL a test builds goes into that basetemp, so no two jobs write the same file.

Every job runs with --release (the slow release-only tests of tests/conftest.py included) unless --quick is given;
the run before a release must not use --quick. Every job that fails is then run again on its own, and only the
jobs that still fail alone are reported as failing. The summary, with the counts per test file, is printed and
written to <out>/summary.txt; each job's log is beside it. Exit status 1 if anything still fails alone.

Set VF1_VANILLA_DIR to a copy of the vanilla game folder first, or the tests that need it skip.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)")

# Measured with pytest --durations on 2026-10-23 (serial, 148 tests, 342 s): test_up_to_28_children.py took 258 s
# (each job pays its ~31 s vf1kids.dll builds once, then ~9-19 s per source mutation) and test_engine.py 45 s;
# every other file is under 25 s and runs as one job.
SPLIT = {"test_up_to_28_children.py": 12, "test_engine.py": 3}


def env() -> dict:
    paths = [str(REPO / "patcher"), str(REPO / "tools")]
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    return dict(os.environ, PYTHONPATH=os.pathsep.join(paths))


def pytest_cmd(args: list[str], basetemp: Path, release: bool) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", f"--rootdir={REPO}",
            f"--basetemp={basetemp}", *(["--release"] if release else []), *args]


def node_ids(test: Path) -> list[str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        f"--rootdir={REPO}", test.relative_to(REPO).as_posix()],
                       cwd=REPO, env=env(), capture_output=True, text=True)
    ids = [line.strip() for line in r.stdout.splitlines() if "::" in line]
    if r.returncode != 0 or not ids:
        raise SystemExit(f"cannot collect {test.name}:\n{r.stdout}{r.stderr}")
    return ids


def jobs() -> list[tuple[str, str, list[str]]]:
    """(job name, test file, pytest arguments)."""
    out = []
    # the split files first, so their long jobs start before the short ones
    for test in sorted((REPO / "tests").glob("test_*.py"), key=lambda p: (-SPLIT.get(p.name, 1), p.name)):
        parts = SPLIT.get(test.name, 1)
        if parts == 1:
            out.append((test.stem, test.name, [test.relative_to(REPO).as_posix()]))
            continue
        ids = node_ids(test)
        for k in range(parts):
            chunk = ids[k::parts]
            if chunk:
                out.append((f"{test.stem}.{k + 1}", test.name, chunk))
    return out


def run(job: tuple[str, str, list[str]], tag: str, out: Path, short: Path, release: bool):
    name, test, args = job
    log = out / f"{tag}_{name}.log"
    start = time.time()
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        rc = subprocess.call(pytest_cmd(args, short / f"{tag}_{name}", release), cwd=REPO, env=env(),
                             stdout=fh, stderr=subprocess.STDOUT)
    lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if COUNT.search(line)]
    counts = {key.rstrip("s") if key.startswith("error") else key: int(n)
              for n, key in COUNT.findall(lines[-1] if lines else "")}
    return name, test, rc, counts, time.time() - start


def total(results, test: str | None = None) -> dict:
    counts: dict = {}
    for _, file, _, found, _ in results:
        if test is None or file == test:
            for key, value in found.items():
                counts[key] = counts.get(key, 0) + value
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="leave out the release-only tests (never before a release)")
    ap.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 4))
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "vf1-parallel-tests")
    a = ap.parse_args()
    release = not a.quick
    short = Path(tempfile.gettempdir()) / "vf1p"
    a.out.mkdir(parents=True, exist_ok=True)
    short.mkdir(parents=True, exist_ok=True)       # pytest makes --basetemp itself, but not its parent
    began = time.time()
    todo = jobs()
    with cf.ThreadPoolExecutor(a.workers) as pool:
        first = list(pool.map(lambda j: run(j, "par", a.out, short, release), todo))
    failed = [r[0] for r in first if r[2] not in (0, 5)]          # 5: no tests collected
    again = [run(j, "solo", a.out, short, release) for j in todo if j[0] in failed]
    still = [r[0] for r in again if r[2] not in (0, 5)]
    files = sorted({r[1] for r in first})
    lines = [f"jobs: {len(todo)} from {len(files)} files  workers: {a.workers}  "
             f"release-only tests: {'included' if release else 'LEFT OUT (--quick)'}  wall: {time.time() - began:.0f} s",
             f"parallel totals: {total(first)}",
             *(f"  {f}: {total(first, f)}" for f in files),
             f"failed in parallel: {len(failed)}: {', '.join(failed) or 'none'}",
             f"run again alone: {total(again)}",
             f"STILL FAILING ALONE: {len(still)}: {', '.join(still) or 'none'}"]
    (a.out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if still else 0


if __name__ == "__main__":
    raise SystemExit(main())
