"""HookVtableSlot (native/vf1fun/vf1fun.cpp) on a fake vtable. The Startup hook for
the Adopt screen can run again, so a second install must hand back the game's
original handler, never a null pointer. A slot that holds a foreign pointer
must be refused and not recorded, and the record table holds 32 slots. The C
function is static, so a small harness built with the same MSVC settings as
native/build.bat includes the source and calls it on a fake vtable. The stock
handler in the fake vtable is code inside the harness executable, which is what
HookVtableSlot accepts as a first-install original. It needs the Visual Studio
2026 toolchain (vcvars32.bat), so the tests skip elsewhere."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

HARNESS = r'''
#include "@SOURCE@"

static int Stock() { return 1; }
static int Replacement() { return 2; }

static unsigned AddressOf(void *p) { return (unsigned)(uintptr_t)p; }

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "second")) {
        unsigned table[4] = { 0x1111, AddressOf((void *)&Stock), 0x3333, 0x4444 };
        unsigned *slot = &table[1];
        unsigned first = 0, second = 0;
        bool ok1 = HookVtableSlot(slot, (void *)&Replacement, &first);
        bool ok2 = HookVtableSlot(slot, (void *)&Replacement, &second);
        printf("first install ok=%d original=%x; second install ok=%d original=%x; slot=%s\n",
               ok1, first, ok2, second, *slot == (unsigned)&Replacement ? "replaced" : "not replaced");
        bool good = ok1 && ok2 && first == AddressOf((void *)&Stock) && second == first
                    && *slot == (unsigned)&Replacement;
        return good ? 0 : 1;
    }
    if (!strcmp(mode, "foreign")) {
        // Another module's trampoline: a page this executable does not own.
        unsigned foreign = AddressOf(VirtualAlloc(NULL, 4096, MEM_COMMIT, PAGE_EXECUTE_READWRITE));
        unsigned table[2] = { foreign, 0x2222 };
        unsigned *slot = &table[0];
        unsigned original = 0xdead;
        bool refused = !HookVtableSlot(slot, (void *)&Replacement, &original);
        bool untouched = *slot == foreign && original == 0xdead;
        // Not recorded: once the slot holds the stock handler again, a first install works.
        *slot = AddressOf((void *)&Stock);
        bool later = HookVtableSlot(slot, (void *)&Replacement, &original);
        bool recordedStock = later && original == AddressOf((void *)&Stock);
        printf("foreign refused=%d untouched=%d later ok=%d original=%x\n",
               refused, untouched, later, original);
        return refused && untouched && recordedStock ? 0 : 1;
    }
    if (!strcmp(mode, "cap")) {
        unsigned table[33];
        for (int i = 0; i < 33; i++)
            table[i] = AddressOf((void *)&Stock);
        unsigned original = 0;
        int installed = 0;
        for (int i = 0; i < 32; i++)
            installed += HookVtableSlot(&table[i], (void *)&Replacement, &original) ? 1 : 0;
        bool thirtyThird = HookVtableSlot(&table[32], (void *)&Replacement, &original);
        printf("installed=%d thirty-third ok=%d slot=%s\n", installed, thirtyThird,
               table[32] == AddressOf((void *)&Stock) ? "untouched" : "changed");
        return installed == 32 && !thirtyThird && table[32] == AddressOf((void *)&Stock) ? 0 : 1;
    }
    return 2;
}
'''


@pytest.fixture(scope="module")
def harness_exe(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("hook_install")
    src = tmp_path / "hook_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    # Not "install" in the name: Windows asks for elevation on setup-like exe names.
    exe = tmp_path / "hook_harness.exe"
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
    return exe


def run_case(exe, mode):
    run = subprocess.run([str(exe), mode], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


SKIP_WITHOUT_TOOLCHAIN = pytest.mark.skipif(
    os.name != "nt" or not VCVARS.is_file(),
    reason="needs the MSVC toolchain (vcvars32.bat) on Windows")


@SKIP_WITHOUT_TOOLCHAIN
def test_second_hook_install_keeps_a_valid_original(harness_exe):
    run_case(harness_exe, "second")


@SKIP_WITHOUT_TOOLCHAIN
def test_foreign_slot_pointer_is_refused_and_not_recorded(harness_exe):
    run_case(harness_exe, "foreign")


@SKIP_WITHOUT_TOOLCHAIN
def test_record_table_stops_at_thirty_two_slots(harness_exe):
    run_case(harness_exe, "cap")
