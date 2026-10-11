// appearance_page.inc -- "Clothing and Hairstyles" page of the Upgrades menu.
//
// Like the Virtual Families 2 store section of the same name, it shows every option: all 50 hairstyles
// (head rows, 0-49) and all 50 outfits (body rows, 0-49) for each gender, drawn from the game's own large
// sprite sheets in its Images folder: female_heads00.png / male_heads00.png (50 rows of 12 frames of
// 56 x 56; the front-facing face is frame 5) and highrez_bodies_final2.png, the big bodies (50 rows of
// 164 x 164; male left, female right). Nothing is shipped: the sheets are read at run time with GDI+
// (part of Windows). Clicking
// an option changes the picked villager's head or body, exactly as Villager Cheats > Change Appearance does
// (CVillager +0x2A60 / +0x2A64), and the Family Tree portrait follows (SyncTreeLook).

#include <algorithm>
using std::min;
using std::max;
#include <gdiplus.h>

enum { ID_AP_LIST = 900, ID_AP_HAIR, ID_AP_OUTFIT, ID_AP_FEMALE, ID_AP_MALE, ID_AP_CANVAS, ID_AP_SCROLL, ID_AP_HINT };

namespace appearance {
using namespace Gdiplus;
static ULONG_PTR gToken;
static Bitmap *gSheet[3];
static const int kHeadCell = 56, kHeadCol = 5, kBodyCell = 164, kPitchHead = 64, kPitchBody = 112;
static bool gOutfits;
static bool gMale;
static int gScroll;  // pixels

static void Start() {
    if (gToken) return;
    GdiplusStartupInput in;
    GdiplusStartup(&gToken, &in, 0);
}
static Bitmap *Sheet(bool outfits, bool male) {
    Bitmap *&b = gSheet[outfits ? 2 : male];  // 0 female heads, 1 male heads, 2 the big bodies (both genders)
    if (!b) {
        wchar_t path[MAX_PATH];
        GetModuleFileNameW(0, path, MAX_PATH);
        wchar_t *slash = wcsrchr(path, L'\\');
        if (slash) *slash = 0;
        wcscat_s(path, MAX_PATH, outfits ? L"\\Images\\highrez_bodies_final2.png"
                                         : (male ? L"\\Images\\male_heads00.png" : L"\\Images\\female_heads00.png"));
        b = new Bitmap(path);
        if (b->GetLastStatus() != Ok) { delete b; b = 0; }
    }
    return b;
}
static int Pitch() { return gOutfits ? kPitchBody : kPitchHead; }
static int Columns(HWND canvas) {
    RECT r; GetClientRect(canvas, &r);
    return max(1, (int)(r.right / Pitch()));
}
static int ContentHeight(HWND canvas) {
    int cols = Columns(canvas);
    return ((50 + cols - 1) / cols) * Pitch();
}
static void UpdateScroll(HWND dlg) {
    HWND canvas = GetDlgItem(dlg, ID_AP_CANVAS);
    RECT r; GetClientRect(canvas, &r);
    int total = ContentHeight(canvas);
    int maxScroll = max(0, total - (int)r.bottom);
    gScroll = max(0, min(gScroll, maxScroll));
    SCROLLINFO si = { sizeof si, SIF_RANGE | SIF_PAGE | SIF_POS, 0, total, (UINT)r.bottom, gScroll, 0 };
    SetScrollInfo(GetDlgItem(dlg, ID_AP_SCROLL), SB_CTL, &si, TRUE);
    InvalidateRect(canvas, 0, TRUE);
}
static int PickedVillager(HWND dlg) {
    HWND list = GetDlgItem(dlg, ID_AP_LIST);
    int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
    return sel < 0 ? -1 : (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
}
static void FillList(HWND dlg, int keep) {
    HWND list = GetDlgItem(dlg, ID_AP_LIST);
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    for (int i = 0; i < VillagerSlots; ++i) {
        if (!VillagerPresent(i)) continue;
        wchar_t line[128];
        swprintf(line, 128, L"%.40hs\t%ls   Hair %d   Outfit %d", (const char *)(Villager(i) + 0x2A44),
                 *(int *)(Villager(i) + 0x2A38) == 1 ? L"Female" : L"Male", *Head(i), *Body(i));
        int row = (int)SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
        SendMessageW(list, LB_SETITEMDATA, row, i);
        if (i == keep) SendMessageW(list, LB_SETCURSEL, row, 0);
    }
    if (SendMessageW(list, LB_GETCURSEL, 0, 0) < 0) SendMessageW(list, LB_SETCURSEL, 0, 0);
}
static void FollowGender(HWND dlg) {
    int who = PickedVillager(dlg);
    if (who < 0) return;
    gMale = *(int *)(Villager(who) + 0x2A38) != 1;
    CheckRadioButton(dlg, ID_AP_FEMALE, ID_AP_MALE, gMale ? ID_AP_MALE : ID_AP_FEMALE);
}
static void Draw(DRAWITEMSTRUCT *d, int who) {
    FillRect(d->hDC, &d->rcItem, (HBRUSH)GetStockObject(WHITE_BRUSH));
    Bitmap *sheet = Sheet(gOutfits, gMale);
    IntersectClipRect(d->hDC, d->rcItem.left, d->rcItem.top, d->rcItem.right, d->rcItem.bottom);
    Graphics g(d->hDC);
    g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
    int cols = max(1, (int)((d->rcItem.right - d->rcItem.left) / Pitch()));
    int current = who < 0 ? -1 : (gOutfits ? *Body(who) : *Head(who));
    bool same = who >= 0 && (*(int *)(Villager(who) + 0x2A38) != 1) == gMale;
    HFONT font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    SelectObject(d->hDC, font);
    SetBkMode(d->hDC, TRANSPARENT);
    for (int n = 0; n < 50; ++n) {
        int x = (n % cols) * Pitch(), y = (n / cols) * Pitch() - gScroll;
        if (y + Pitch() < 0 || y > d->rcItem.bottom) continue;
        if (same && n == current) {
            RECT hi = { x, y, x + Pitch() - 2, y + Pitch() - 2 };
            HBRUSH b = CreateSolidBrush(RGB(255, 214, 120));
            FillRect(d->hDC, &hi, b);
            DeleteObject(b);
        }
        if (sheet) {
            if (gOutfits) {
                g.DrawImage(sheet, Rect(x + 4, y + 4, 96, 96), (gMale ? 0 : 1) * kBodyCell, n * kBodyCell, kBodyCell, kBodyCell, UnitPixel);
            } else {
                g.DrawImage(sheet, Rect(x + 8, y + 4, 48, 48), kHeadCol * kHeadCell, n * kHeadCell, kHeadCell, kHeadCell, UnitPixel);
            }
        }
        wchar_t num[8];
        swprintf(num, 8, L"%d", n);
        RECT t = { x, y + Pitch() - 16, x + Pitch() - 2, y + Pitch() - 2 };
        DrawTextW(d->hDC, num, -1, &t, DT_CENTER | DT_SINGLELINE);
    }
}
static void Apply(HWND dlg, int n) {
    int who = PickedVillager(dlg);
    if (who < 0) return;
    bool otherGender = (*(int *)(Villager(who) + 0x2A38) != 1) != gMale;
    wchar_t text[200];
    swprintf(text, 200, L"Change %.40hs's %ls to %ls #%d?%ls", (const char *)(Villager(who) + 0x2A44),
             gOutfits ? L"outfit" : L"hairstyle", gMale ? L"male" : L"female", n,
             otherGender ? L"\n\nThis is the other gender's look. It is drawn from the same row number." : L"");
    if (!Confirm(dlg, text)) return;
    // The head and body rows are the same 0-49 numbers for both genders (each gender draws them from its own sheet).
    if (gOutfits) *Body(who) = n; else *Head(who) = n;
    SyncTreeLook(who);
    FillList(dlg, who);
    InvalidateRect(GetDlgItem(dlg, ID_AP_CANVAS), 0, TRUE);
}
static WNDPROC gCanvasProc;
// The canvas is a static; its own proc turns a click into the cell clicked (the click position is in the message).
static LRESULT CALLBACK CanvasProc(HWND wnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_LBUTTONUP) {
        SendMessageW(GetParent(wnd), WM_APP, (WPARAM)(short)LOWORD(lp), (LPARAM)(short)HIWORD(lp));
        return 0;
    }
    return CallWindowProcW(gCanvasProc, wnd, msg, wp, lp);
}
static INT_PTR CALLBACK Proc(HWND dlg, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_INITDIALOG:
        Start();
        gCanvasProc = (WNDPROC)SetWindowLongPtrW(GetDlgItem(dlg, ID_AP_CANVAS), GWLP_WNDPROC, (LONG_PTR)CanvasProc);
        gOutfits = false; gScroll = 0;
        { int stop = 70; SendMessageW(GetDlgItem(dlg, ID_AP_LIST), LB_SETTABSTOPS, 1, (LPARAM)&stop); }
        FillList(dlg, -1);
        FollowGender(dlg);
        CheckRadioButton(dlg, ID_AP_HAIR, ID_AP_OUTFIT, ID_AP_HAIR);
        UpdateScroll(dlg);
        return TRUE;
    case WM_DRAWITEM:
        if (wp == ID_AP_CANVAS) { Draw((DRAWITEMSTRUCT *)lp, PickedVillager(dlg)); return TRUE; }
        return FALSE;
    case WM_VSCROLL: {
        if ((HWND)lp != GetDlgItem(dlg, ID_AP_SCROLL)) return FALSE;
        SCROLLINFO si = { sizeof si, SIF_ALL };
        GetScrollInfo((HWND)lp, SB_CTL, &si);
        int pos = si.nPos;
        switch (LOWORD(wp)) {
        case SB_LINEUP: pos -= 24; break;
        case SB_LINEDOWN: pos += 24; break;
        case SB_PAGEUP: pos -= si.nPage; break;
        case SB_PAGEDOWN: pos += si.nPage; break;
        case SB_THUMBTRACK: case SB_THUMBPOSITION: pos = si.nTrackPos; break;
        }
        gScroll = pos;
        UpdateScroll(dlg);
        return TRUE;
    }
    case WM_APP: {  // a click on the canvas at (wp, lp)
        HWND canvas = GetDlgItem(dlg, ID_AP_CANVAS);
        int cols = Columns(canvas), px = (int)wp, py = (int)lp;
        int n = ((py + gScroll) / Pitch()) * cols + px / Pitch();
        if (px >= 0 && py >= 0 && px / Pitch() < cols && n >= 0 && n < 50) Apply(dlg, n);
        return TRUE;
    }
    case WM_MOUSEWHEEL:
        gScroll -= (short)HIWORD(wp) / 120 * 48;
        UpdateScroll(dlg);
        return TRUE;
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (id == ID_AP_LIST && HIWORD(wp) == LBN_SELCHANGE) {
            FollowGender(dlg);
            UpdateScroll(dlg);
        } else if (id == ID_AP_HAIR || id == ID_AP_OUTFIT) {
            gOutfits = id == ID_AP_OUTFIT; gScroll = 0;
            UpdateScroll(dlg);
        } else if (id == ID_AP_FEMALE || id == ID_AP_MALE) {
            gMale = id == ID_AP_MALE;
            UpdateScroll(dlg);
        } else if (id == IDOK || id == IDCANCEL) {
            EndDialog(dlg, 0);
        }
        return TRUE;
    }
    case WM_CLOSE:
        EndDialog(dlg, 0);
        return TRUE;
    }
    return FALSE;
}
}  // namespace appearance

static void ShowAppearance(HWND owner) {
    static Template t;
    using namespace appearance;
    t.Begin(L"Clothing and Hairstyles", 330, 300, 9);
    t.Item(LISTBOX, LBS_NOTIFY | LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 8, 8, 314, 62, ID_AP_LIST, L"");
    t.Item(BUTTON, BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 8, 76, 70, 12, ID_AP_HAIR, L"Hairstyles");
    t.Item(BUTTON, BS_AUTORADIOBUTTON, 82, 76, 60, 12, ID_AP_OUTFIT, L"Outfits");
    t.Item(BUTTON, BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 190, 76, 60, 12, ID_AP_FEMALE, L"Female");
    t.Item(BUTTON, BS_AUTORADIOBUTTON, 254, 76, 60, 12, ID_AP_MALE, L"Male");
    t.Item(STATIC, SS_OWNERDRAW | SS_NOTIFY | WS_BORDER, 8, 92, 300, 176, ID_AP_CANVAS, L"");
    t.Item(0x84, SBS_VERT, 308, 92, 12, 176, ID_AP_SCROLL, L"");
    t.Item(STATIC, SS_LEFT, 8, 274, 230, 20, ID_AP_HINT, L"Pick a villager, then click a hairstyle or outfit to give them.");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 247, 278, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, appearance::Proc, 0);
}
