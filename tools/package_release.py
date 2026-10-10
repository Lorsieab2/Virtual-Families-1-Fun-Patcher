#!/usr/bin/env python3
"""Package a player release: outputs/VF1-Patcher-<version>.zip.

usage: package_release.py VERSION
Needs build/vf1fun.dll (native/build.bat) and patcher/stub.json
(tools/build_stub.py). The zip holds one folder, "Virtual Families 1
Patcher", with the launcher, the instructions and patcher/ (the two scripts,
stub.json and vf1fun.dll). No game files.
"""
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "Virtual Families 1 Patcher"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    version = sys.argv[1]
    files = {
        f"{TOP}/Launch Virtual Families 1 Patcher.bat": ROOT / "release" / "Launch Virtual Families 1 Patcher.bat",
        f"{TOP}/How to Use.txt": ROOT / "release" / "How to Use.txt",
        f"{TOP}/patcher/vf1_patcher.py": ROOT / "patcher" / "vf1_patcher.py",
        f"{TOP}/patcher/vf1_patcher_gui.py": ROOT / "patcher" / "vf1_patcher_gui.py",
        f"{TOP}/patcher/stub.json": ROOT / "patcher" / "stub.json",
        f"{TOP}/patcher/vf1fun.dll": ROOT / "build" / "vf1fun.dll",
    }
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        print("missing:", *missing, sep="\n  ")
        return 1
    out = ROOT / "outputs" / f"VF1-Patcher-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in files.items():
            z.write(path, name)
    data = out.read_bytes()
    print(f"{out}  {len(data):,} bytes  SHA-256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
