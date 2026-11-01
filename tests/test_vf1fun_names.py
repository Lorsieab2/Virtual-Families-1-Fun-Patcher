"""Names in vf1fun.dll's own windows (Spawn Child, Adopt Outside Child, the Family, Appearance, Villager Cheats and
Services pages): read by the patcher's one rule and stored as UTF-8 cut between whole characters, the same as
patcher/vf1_text.py. The real compiled vf1fun.dll's own code runs in Unicorn (kids_emu); Windows'
MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS) is stood in for by Python's strict UTF-8 decoder."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

pytest.importorskip("pefile")
pytest.importorskip("unicorn")

import vf1_text  # noqa: E402

VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")


@pytest.fixture(scope="module")
def emu(tmp_path_factory, vanilla_dir):
    if os.name != "nt" or not VCVARS.is_file():
        pytest.skip("needs the MSVC toolchain (vcvars32.bat) on Windows")
    import shutil
    import kids_emu as K
    work = tmp_path_factory.mktemp("fun_build")
    shutil.copytree(ROOT / "native", work / "native")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer"
    r = subprocess.run(["cmd.exe", "/c", str(work / "native" / "build.bat")], capture_output=True, text=True,
                       env=dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}"))
    assert r.returncode == 0, r.stdout + r.stderr
    e = K.Emu(vanilla_dir / "Virtual Families.exe", work / "build" / "vf1fun.dll", 0)

    def multi_to_wide(em):
        cp, flags, src, n, dst, size = (em.arg(i) for i in range(6))
        assert cp == 65001 and flags == 8
        try:
            text = em.read(src, n).decode("utf-8")
        except UnicodeDecodeError:
            return 0, 24
        data = text.encode("utf-16-le")
        if len(data) // 2 > size:
            return 0, 24
        em.write(dst, data)
        return len(data) // 2, 24
    e.imports["MultiByteToWideChar"] = multi_to_wide
    return e


def fit(emu, name: str, room: int) -> bytes:
    src = emu.alloc(len(name) * 4 + 4)
    emu.write(src, name.encode("utf-16-le", "surrogatepass") + b"\0\0")
    out = emu.alloc(room + 8, fill=0xCC)
    n = emu.call(emu.dll_export("VF1Fun_FitName"), (src, out, room))
    data = emu.read(out, room + 8)
    assert data[n] == 0 and data[room + 1:] == b"\xcc" * 7     # never past the room and its NUL
    return data[:n]


def name_w(emu, data: bytes, cap: int = 0x19) -> str:
    src = emu.alloc(len(data) + 4)
    emu.write(src, data + b"\0")
    return emu.wstr(emu.call(emu.dll_export("VF1Fun_NameW"), (src, cap)))


@pytest.mark.parametrize("name", ["Ann", "Zo\u00eb", "\u0130lkay \u011e\u00fcl", "\u65e5\u672c\u8a9e\u306e\u540d\u524d",
                                  "Mia \U0001f44d\U0001f3fd", "e\u0301e\u0301e\u0301", "\U0001202d\U00012000 Ninsun",
                                  "Ver" + "y" * 40 + " long"])
def test_a_typed_name_is_stored_as_the_patcher_stores_it(emu, name):
    assert fit(emu, name, 24) == vf1_text.encode(vf1_text.cut_to_bytes(name, 24))


def test_control_characters_and_lone_surrogates_are_never_stored(emu):
    assert fit(emu, "A\tB\x85C", 24) == b"ABC"
    assert fit(emu, "X\ud800Y", 24) == b"XY"


@pytest.mark.parametrize("data", [b"Smith", "Zo\u00eb".encode(), "\u65e5\u672c".encode(), b"Caf\xe9",
                                  b"\x93Hi\x94", "\U0001f44d".encode()])
def test_a_stored_name_reads_by_the_one_rule(emu, data):
    assert name_w(emu, data) == vf1_text.decode(data)
