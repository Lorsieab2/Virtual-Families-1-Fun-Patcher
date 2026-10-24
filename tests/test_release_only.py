"""Every entry of RELEASE_ONLY (tests/conftest.py) names a test that really exists, so a rename can never
quietly turn a release-only test back into an ordinary one or leave a dead entry behind."""
import subprocess
import sys

from conftest import RELEASE_ONLY, ROOT


def collected(files: list[str]) -> set[str]:
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "--release", "-p", "no:cacheprovider",
                        f"--rootdir={ROOT}", *files], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return {line.strip() for line in r.stdout.splitlines() if "::" in line}


def test_every_release_only_entry_is_a_real_test():
    assert len(set(RELEASE_ONLY)) == len(RELEASE_ONLY), "an entry is listed twice"
    found = collected(sorted({entry.split("::", 1)[0] for entry in RELEASE_ONLY}))
    missing = [entry for entry in RELEASE_ONLY if entry not in found]
    assert not missing, missing
