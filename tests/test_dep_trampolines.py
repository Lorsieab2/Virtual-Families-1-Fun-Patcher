"""DEP: a trampoline or code-cave buffer in a DLL's data section is not executable. The emulator does not enforce
that, so it passes in Unicorn and then crashes in the real game. Every byte array a DLL builds code in must be made
PAGE_EXECUTE_READWRITE with VirtualProtect before any hook points at it, or the code must live in .text as
__declspec(naked) functions. This is a source-level check of every DLL's native source."""
import re

from conftest import ROOT

NATIVE = ROOT / "native"
ARRAY = re.compile(r"static\s+unsigned\s+char\s+(\w+)\s*\[\s*([^\]]+?)\s*\]\s*;")
CODE_NAME = re.compile(r"tramp|cave|thunk|stub|detour|code", re.I)


def sources():
    for p in sorted(NATIVE.rglob("*")):
        if p.suffix in (".c", ".cpp", ".inc", ".h"):
            yield p, p.read_text(encoding="utf-8", errors="replace")


def test_every_trampoline_array_is_made_executable():
    found = []
    for path, text in sources():
        for m in ARRAY.finditer(text):
            name = m.group(1)
            if not CODE_NAME.search(name):
                continue
            found.append((path.name, name))
            protect = re.search(
                r"VirtualProtect\s*\(\s*(?:\(\s*\w+\s*\*?\s*\)\s*)?&?" + re.escape(name) + r"\s*,[^;]*PAGE_EXECUTE_READWRITE",
                text)
            assert protect, f"{path.name}: {name} is a code buffer in the data section and is never VirtualProtect-ed to " \
                            "PAGE_EXECUTE_READWRITE (DEP crashes the real game; emulation does not)"
    # the two DLLs that build trampolines today, so a rename cannot make this test vacuous
    assert ("vf1kids.cpp", "Trampolines") in found and ("vf1logs.cpp", "Trampolines") in found, found


def test_the_protect_comes_before_the_first_hook_is_written():
    for dll in ("vf1kids", "vf1logs"):
        text = (NATIVE / dll / f"{dll}.cpp").read_text(encoding="utf-8")
        apply_body = text[text.index("static bool Apply(Plan &plan) {"):]
        protect = apply_body.index("VirtualProtect(Trampolines, sizeof(Trampolines), PAGE_EXECUTE_READWRITE")
        assert protect < apply_body.index("WriteCode(w.va"), dll

def test_the_entry_hooks_run_the_stock_code_through_naked_functions():
    """vf1text's wrapper and vf1tr's DrawString / wrapper trampolines are code in .text, never data."""
    tr = (NATIVE / "vf1tr" / "screen_tr.inc").read_text(encoding="utf-8")
    for name in ("stock_draw_string", "stock_wrap"):
        assert f"__declspec(naked) static void {name}(void)" in tr, name
    names = (NATIVE / "vf1text" / "names.inc").read_text(encoding="utf-8")
    assert "__declspec(naked) static void WrapStock()" in names
