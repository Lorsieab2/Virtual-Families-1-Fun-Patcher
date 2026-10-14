"""HookVtableSlot (native/vf1fun/vf1fun.cpp) run twice. The Startup hook for the
Adopt screen can run again, and the second install must still hand back the
game's original handler, never a null pointer. The C function is static, so a
small harness built with the same MSVC settings as native/build.bat includes
the source and calls it on a fake vtable. It needs the Visual Studio 2026
toolchain (vcvars32.bat), so the test skips elsewhere."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

HARNESS = r'''
#include "@SOURCE@"

static void Replacement() {}

int main() {
    unsigned table[4] = { 0x1111, 0x2222, 0x3333, 0x4444 };
    unsigned *slot = &table[2];
    unsigned first = 0, second = 0;
    bool ok1 = HookVtableSlot(slot, (void *)&Replacement, &first);
    bool ok2 = HookVtableSlot(slot, (void *)&Replacement, &second);
    printf("first install ok=%d original=%x; second install ok=%d original=%x; slot=%s\n",
           ok1, first, ok2, second, *slot == (unsigned)&Replacement ? "replaced" : "not replaced");
    bool good = ok1 && ok2 && first == 0x3333 && second == 0x3333 && *slot == (unsigned)&Replacement;
    return good ? 0 : 1;
}
'''


@pytest.mark.skipif(os.name != "nt" or not VCVARS.is_file(),
                    reason="needs the MSVC toolchain (vcvars32.bat) on Windows")
def test_second_hook_install_keeps_a_valid_original(tmp_path):
    src = tmp_path / "hook_twice.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    exe = tmp_path / "hook_twice.exe"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 "{src}" /Fo"{tmp_path}\\\\" /Fe"{exe}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib || exit /b 1\r\n",
        encoding="ascii")
    # vcvars32.bat looks for vswhere.exe on PATH; the Visual Studio installer folder holds it.
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
