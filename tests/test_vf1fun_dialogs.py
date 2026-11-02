"""vf1fun.dll's own Win32 windows (the Upgrades menu and its pages), made for real with the Windows dialog manager.

A small harness built with native/build.bat's MSVC settings includes native/vf1fun/vf1fun.cpp and takes each
page's in-memory dialog template (the same Template the DLL hands DialogBoxIndirectParamW). Each page is created
with CreateDialogIndirectParamW and a stand-in dialog procedure (the real ones read the game's memory):

* every control the page's code adds is in the template (DLGTEMPLATE.cdit equals the controls written; a
  hand-written count once said 29 for the Family page's 31 controls, so Windows made only the first 29 and the page
  had no Evict Family and no Close button), and Windows makes every one of them, Close (IDOK) included;
* every control lies inside the page, in dialog units and in pixels at 100%, 125% and 150% (96, 120 and 144 DPI:
  the dialog font's base units at that DPI) and in the window Windows really made at this machine's DPI;
* the controls that show names (the Family page's Name box and family line, the Services, Villager Cheats and
  Clothing and Hairstyles name lists) draw Cuneiform and the other scripts, not the empty "missing letter" box:
  each control is drawn (WM_PRINTCLIENT) with a name and compared with the same control drawing two code points no
  font has. With the dialog font alone (the old way) Cuneiform IS drawn as missing boxes, so the check can see it;
* the Name box is still a plain EDIT control, not subclassed, with the same text limit, and it keeps a pasted
  supplementary-plane name exactly (copy and paste are the EDIT control's own).

It needs the Visual Studio 2026 toolchain (vcvars32.bat), so the tests skip elsewhere."""
import os
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

SOURCE = ROOT / "native" / "vf1fun" / "vf1fun.cpp"
VCVARS = Path(r"C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat")

HARNESS = r'''
#include "@SOURCE@"

struct Page { const char *name; Template &(*get)(); };
static const Page kPages[] = {
    { "Upgrades Menu", UpgradesTemplate }, { "Cheat Upgrades", CheatsTemplate },
    { "Villager Cheats", VillagerCheatsTemplate }, { "Flea Market", FleaMarketTemplate },
    { "Store Cheats", StoreCheatsTemplate }, { "House and Yard", HouseTemplate },
    { "Special Upgrades", PurchasesTemplate }, { "Time Controls", TimeTemplate },
    { "Family", FamilyTemplate }, { "Clothing and Hairstyles", AppearanceTemplate },
    { "Services", ServicesTemplate }, { "Patcher Achievements", AchievementsTemplate },
};

struct Ctl { short x, y, cx, cy; WORD id, cls; };
static int gFail;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); ++gFail; } } while (0)

// Walks the template the way the dialog manager reads it; returns the number of controls found in its words.
static int Walk(Template &t, Ctl *out, int max, wchar_t *face) {
    const WORD *w = (const WORD *)t.Get();
    int n = sizeof(DLGTEMPLATE) / 2;
    n += 2;                                   // menu, class
    while (w[n++]) {}                         // title
    n++;                                      // point size
    int f = 0; while ((face[f] = w[n++]) != 0) ++f;
    int k = 0;
    while (n < t.Size()) {
        if (n % 2) ++n;
        const DLGITEMTEMPLATE *it = (const DLGITEMTEMPLATE *)(w + n);
        n += sizeof(DLGITEMTEMPLATE) / 2;
        WORD cls = w[n] == 0xFFFF ? w[n + 1] : 0;
        n += 2;
        while (w[n++]) {}
        n++;                                  // creation data
        if (k < max) { out[k].x = it->x; out[k].y = it->y; out[k].cx = it->cx; out[k].cy = it->cy; out[k].id = it->id; out[k].cls = cls; }
        ++k;
    }
    return k;
}

static INT_PTR CALLBACK Stand(HWND, UINT msg, WPARAM, LPARAM) { return msg == WM_INITDIALOG; }

static BOOL CALLBACK CountChild(HWND, LPARAM p) { ++*(int *)p; return TRUE; }

static void BaseUnits(const wchar_t *face, int pt, int dpi, int *bx, int *by) {
    HDC dc = CreateCompatibleDC(0);
    HFONT font = CreateFontW(-MulDiv(pt, dpi, 72), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, 0, 0, face);
    HGDIOBJ old = SelectObject(dc, font);
    TEXTMETRICW tm; GetTextMetricsW(dc, &tm);
    SIZE s; GetTextExtentPoint32W(dc, L"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", 52, &s);
    *bx = (s.cx / 26 + 1) / 2;
    *by = tm.tmHeight;
    SelectObject(dc, old); DeleteObject(font); DeleteDC(dc);
}

static int Layout() {
    for (const Page &p : kPages) {
        Template &t = p.get();
        DLGTEMPLATE *d = t.Get();
        Ctl c[128]; wchar_t face[64];
        int found = Walk(t, c, 128, face);
        printf("%s: %d controls, %dx%d\n", p.name, found, d->cx, d->cy);
        CHECK(t.Dropped() == 0, "%s: %d controls left out of the template", p.name, t.Dropped());
        CHECK(found == d->cdit, "%s: the template holds %d controls but says %d", p.name, found, d->cdit);
        bool close = false;
        for (int i = 0; i < found && i < 128; ++i) {
            if (c[i].id == IDOK) close = true;
            CHECK(c[i].x >= 0 && c[i].y >= 0 && c[i].x + c[i].cx <= d->cx && c[i].y + c[i].cy <= d->cy,
                  "%s: control %d (id %d) at %d,%d %dx%d is outside the %dx%d page (dialog units)", p.name, i,
                  (short)c[i].id, c[i].x, c[i].y, c[i].cx, c[i].cy, d->cx, d->cy);
            for (int dpi = 96; dpi <= 144; dpi += 24) {
                int bx, by; BaseUnits(face, 9, dpi, &bx, &by);
                int r = MulDiv(c[i].x + c[i].cx, bx, 4), b = MulDiv(c[i].y + c[i].cy, by, 8);
                int W = MulDiv(d->cx, bx, 4), H = MulDiv(d->cy, by, 8);
                CHECK(r <= W && b <= H, "%s at %d DPI: control id %d ends at %d,%d past the %dx%d client area",
                      p.name, dpi, (short)c[i].id, r, b, W, H);
            }
        }
        CHECK(close, "%s: no Close (IDOK) button", p.name);
        HWND dlg = CreateDialogIndirectParamW(GetModuleHandleW(0), d, 0, Stand, 0);
        CHECK(dlg != 0, "%s: CreateDialogIndirectParamW failed (%lu)", p.name, GetLastError());
        if (!dlg) continue;
        int children = 0;
        EnumChildWindows(dlg, CountChild, (LPARAM)&children);
        CHECK(children == found, "%s: Windows made %d of the %d controls", p.name, children, found);
        HWND ok = GetDlgItem(dlg, IDOK);
        CHECK(ok != 0, "%s: GetDlgItem(IDOK) failed", p.name);
        wchar_t text[32] = L"";
        if (ok) GetWindowTextW(ok, text, 32);
        CHECK(!wcscmp(text, L"Close"), "%s: IDOK is not the Close button", p.name);
        RECT client; GetClientRect(dlg, &client);
        for (int i = 0; i < found && i < 128; ++i) {
            if (c[i].id == 0xFFFF) continue;
            HWND w = GetDlgItem(dlg, c[i].id);
            CHECK(w != 0, "%s: control id %d was not made", p.name, c[i].id);
            if (!w) continue;
            RECT r; GetWindowRect(w, &r);
            MapWindowPoints(0, dlg, (POINT *)&r, 2);
            CHECK(r.left >= 0 && r.top >= 0 && r.right <= client.right && r.bottom <= client.bottom,
                  "%s: control id %d at %ld,%ld-%ld,%ld is outside the %ldx%ld client area", p.name, c[i].id,
                  r.left, r.top, r.right, r.bottom, client.right, client.bottom);
        }
        DestroyWindow(dlg);
    }
    return gFail ? 1 : 0;
}

// ------------------------------------------------------------------ names in any script
static unsigned Draw(HWND w, int *ink) {
    RECT r; GetClientRect(w, &r);
    HDC wdc = GetDC(w), mdc = CreateCompatibleDC(wdc);
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof bi.bmiHeader; bi.bmiHeader.biWidth = r.right; bi.bmiHeader.biHeight = -r.bottom;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32;
    void *bits; HBITMAP bm = CreateDIBSection(mdc, &bi, DIB_RGB_COLORS, &bits, 0, 0);
    HGDIOBJ old = SelectObject(mdc, bm);
    HBRUSH white = CreateSolidBrush(0xFFFFFF); FillRect(mdc, &r, white); DeleteObject(white);
    SendMessageW(w, WM_PRINTCLIENT, (WPARAM)mdc, PRF_CLIENT | PRF_ERASEBKGND);
    GdiFlush();
    const DWORD *p = (const DWORD *)bits;
    int n = r.right * r.bottom;
    unsigned h = 2166136261u;
    // ink: pixels unlike the most common one (the background)
    DWORD bg = p[n / 2 + r.right - 2] & 0xFFFFFF;
    int same = 0;
    for (int i = 0; i < n; ++i) { h = (h ^ (p[i] & 0xFFFFFF)) * 16777619u; same += (p[i] & 0xFFFFFF) == bg; }
    *ink = n - same;
    SelectObject(mdc, old); DeleteObject(bm); DeleteDC(mdc); ReleaseDC(w, wdc);
    return h;
}

static void Show(HWND w, const wchar_t *s) {
    wchar_t cls[16]; GetClassNameW(w, cls, 16);
    if (!_wcsicmp(cls, L"ListBox")) { SendMessageW(w, LB_RESETCONTENT, 0, 0); SendMessageW(w, LB_ADDSTRING, 0, (LPARAM)s); }
    else SetWindowTextW(w, s);
}

// One character at a time, so a single missing letter shows: each is compared with a code point no font has.
static const wchar_t kMissing[] = L"\U0010FFFD";                 // private use, plane 16
static const struct { const char *name; const wchar_t *letters; } kScripts[] = {
    { "Cuneiform", L"\U0001208D\U00012000\U0001202D" }, { "Egyptian", L"\U00013000\U00013080" },
    { "Gothic", L"\U00010330\U00010331" }, { "Latin", L"AZ\u00EB\u00DF" }, { "Turkish", L"\u0130\u0131\u011F\u015F" },
    { "Polish", L"\u0141\u017A" }, { "Vietnamese", L"\u1EA0\u1EB7" }, { "Greek", L"\u03A9\u03B1" },
    { "Cyrillic", L"\u0416\u044F" }, { "Armenian", L"\u0531\u0561" }, { "Georgian", L"\u10D0\u10D1" },
    { "Hebrew", L"\u05D0\u05D1" }, { "Arabic", L"\u0628\u0627" }, { "Japanese", L"\u65E5\u672C\u306B" },
    { "Korean", L"\uAC00\uD55C" }, { "Chinese Ext B", L"\U00020000\U0002A6D6" }, { "emoji", L"\U0001F4A9\U0001F44D" },
    { "Thai", L"\u0E01\u0E02" }, { "Devanagari", L"\u0905\u0906" }, { "Ethiopic", L"\u1200\u1201" },
    { "Cherokee", L"\u13A0\u13A1" },
};

static bool Tofu(HWND w, const wchar_t *letter, int *ink) {
    int missingInk;
    Show(w, kMissing); unsigned missing = Draw(w, &missingInk);
    Show(w, letter); unsigned drawn = Draw(w, ink);
    return drawn == missing;
}

// the next letter (one code point) of s into out; returns the rest
static const wchar_t *NextLetter(const wchar_t *s, wchar_t *out) {
    int n = (s[0] >= 0xD800 && s[0] < 0xDC00) ? 2 : 1;
    memcpy(out, s, n * 2); out[n] = 0;
    return s + n;
}

struct NameCtl { const char *page; Template &(*get)(); int id; };

static int Names() {
    using namespace appearance;
    const NameCtl kCtls[] = {
        { "Family Name box", FamilyTemplate, ID_FA_NAME }, { "Family line", FamilyTemplate, ID_FA_STATUS },
        { "Services list", ServicesTemplate, ID_SV_WHO }, { "Villager Cheats list", VillagerCheatsTemplate, ID_VC_LIST },
        { "Clothing and Hairstyles list", AppearanceTemplate, ID_AP_LIST },
    };
    // Windows' font fallback in these controls works only in a shown window (as in the game), so each page is shown
    // far off the screen, owned by an off-screen tool window (no taskbar button) and never activated.
    HWND owner = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, L"STATIC", L"", WS_POPUP, -20000, -20000, 10, 10,
                                 0, 0, 0, 0);
    ShowWindow(owner, SW_SHOWNOACTIVATE);
    for (const NameCtl &n : kCtls) {
        HWND dlg = CreateDialogIndirectParamW(GetModuleHandleW(0), n.get().Get(), owner, Stand, 0);
        SetWindowPos(dlg, 0, -20000, -20000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        HWND w = GetDlgItem(dlg, n.id);
        int ink;
        // the dialog font alone: Cuneiform is drawn as missing boxes (what the owner saw), so the check can see it
        CHECK(Tofu(w, L"\U0001208D", &ink), "%s: the dialog font now draws Cuneiform; the check is stale", n.page);
        CHECK(NameFont(dlg) != 0, "%s: no name font", n.page);
        // as the page's WM_INITDIALOG leaves the control
        UseNameFont(dlg, n.id);
        for (const auto &s : kScripts) {
            wchar_t letter[3];
            for (const wchar_t *p = s.letters; *p;) {
                p = NextLetter(p, letter);
                bool tofu = Tofu(w, letter, &ink);
                CHECK(!tofu && ink > 0, "%s: a %s letter (U+%04X) is drawn as a missing box (ink %d)", n.page, s.name,
                      letter[1] ? 0x10000 + ((letter[0] - 0xD800) << 10) + (letter[1] - 0xDC00) : letter[0], ink);
            }
        }
        DestroyWindow(dlg);
    }
    DestroyWindow(owner);
    printf("names checked in %d controls, %d scripts\n", (int)(sizeof kCtls / sizeof kCtls[0]), (int)(sizeof kScripts / sizeof kScripts[0]));
    return gFail ? 1 : 0;
}

// The Name box is the EDIT control's own: not subclassed, the same limit, a pasted name kept exactly.
static int NameBox() {
    HWND dlg = CreateDialogIndirectParamW(GetModuleHandleW(0), FamilyTemplate().Get(), 0, Stand, 0);
    HWND w = GetDlgItem(dlg, ID_FA_NAME);
    SendMessageW(w, EM_LIMITTEXT, VF1_NAME_BOX_BYTES, 0);   // as FamilyProc's WM_INITDIALOG
    UseNameFont(dlg, ID_FA_NAME);
    wchar_t cls[16]; GetClassNameW(w, cls, 16);
    CHECK(!_wcsicmp(cls, L"Edit"), "the Name box is a %ls, not an EDIT control", cls);
    WNDCLASSEXW wc = { sizeof wc };
    GetClassInfoExW(0, L"Edit", &wc);
    CHECK((WNDPROC)GetWindowLongPtrW(w, GWLP_WNDPROC) == wc.lpfnWndProc, "the Name box is subclassed");
    CHECK(SendMessageW(w, EM_GETLIMITTEXT, 0, 0) == VF1_NAME_BOX_BYTES, "the Name box's limit changed");
    // EM_REPLACESEL is what the EDIT control's own paste (WM_PASTE, Ctrl+V) does with the clipboard's text
    const wchar_t *name = L"\U0001208D Ninsun \U0001F44D\U0001F3FD";
    SendMessageW(w, EM_REPLACESEL, TRUE, (LPARAM)name);
    wchar_t got[VF1_NAME_BOX_BYTES + 1];
    GetDlgItemTextW(dlg, ID_FA_NAME, got, VF1_NAME_BOX_BYTES + 1);   // as FamilyProc reads it
    CHECK(!wcscmp(got, name), "the Name box changed a pasted name");
    DestroyWindow(dlg);
    return gFail ? 1 : 0;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "layout")) return Layout();
    if (!strcmp(mode, "names")) return Names();
    if (!strcmp(mode, "namebox")) return NameBox();
    return 2;
}
'''

SKIP_WITHOUT_TOOLCHAIN = pytest.mark.skipif(
    os.name != "nt" or not VCVARS.is_file(),
    reason="needs the MSVC toolchain (vcvars32.bat) on Windows")


@pytest.fixture(scope="module")
def harness_exe(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("fun_dialogs")
    src = tmp_path / "dialogs_harness.cpp"
    src.write_text(HARNESS.replace("@SOURCE@", SOURCE.as_posix()), encoding="utf-8")
    exe = tmp_path / "dialogs_harness.exe"
    script = tmp_path / "build_harness.bat"
    script.write_text(
        "@echo off\r\n"
        f'call "{VCVARS}" >nul || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /EHsc /W3 /utf-8 "{src}" /Fo"{tmp_path}\\\\" /Fe"{exe}" '
        "/link user32.lib kernel32.lib shell32.lib gdiplus.lib gdi32.lib /MANIFEST:EMBED "
        "\"/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' "
        "processorArchitecture='x86' publicKeyToken='6595b64144ccf1df' language='*'\" || exit /b 1\r\n",
        encoding="ascii")
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer"
    env = dict(os.environ, PATH=f"{installer};{os.environ.get('PATH', '')}")
    build = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True, env=env)
    assert build.returncode == 0, build.stdout + build.stderr
    return exe


def run_case(exe, mode):
    run = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout


@SKIP_WITHOUT_TOOLCHAIN
def test_every_page_shows_every_control_inside_it_at_100_125_and_150_percent(harness_exe):
    out = run_case(harness_exe, "layout")
    assert "Family: 31 controls" in out


def _has_segoe_ui_historic():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
            winreg.QueryValueEx(key, "Segoe UI Historic (TrueType)")
        return True
    except OSError:
        return False


@SKIP_WITHOUT_TOOLCHAIN
def test_names_in_any_script_are_drawn_not_as_missing_boxes(harness_exe):
    if not _has_segoe_ui_historic():
        pytest.skip("needs Windows' Segoe UI Historic")
    run_case(harness_exe, "names")


@SKIP_WITHOUT_TOOLCHAIN
def test_the_name_box_is_the_edit_controls_own(harness_exe):
    run_case(harness_exe, "namebox")


def test_no_vf1fun_window_blocks_copy_and_paste():
    """Ctrl+C / Ctrl+V / Ctrl+X in vf1fun's own windows are the EDIT controls' own: nothing in the DLL hooks the
    keyboard, filters WM_CHAR or runs its own message loop (the pages are DialogBoxIndirectParamW's modal loop), and
    the only subclassed control is the Clothing and Hairstyles picture canvas."""
    import re
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in (ROOT / "native" / "vf1fun").glob("*.*"))
    for banned in ("SetWindowsHookEx", "WM_CHAR", "WM_KEYDOWN", "GetMessage", "PeekMessage", "TranslateAccelerator",
                   "IsDialogMessage", "WM_PASTE", "WM_GETDLGCODE"):
        assert banned not in text, banned
    assert re.findall(r"SetWindowLongPtrW\(GetDlgItem\(dlg, (\w+)\), GWLP_WNDPROC", text) == ["ID_AP_CANVAS"]
