// vf1fun.dll -- the Virtual Families 1 Patcher's companion.
//
// The patched executable calls VF1Fun_StoreCreated(scene) at the end of the
// store screen's constructor (see patcher/vf1_patcher.py). This adds an
// "Upgrades" button to that screen and takes over the screen's HandleMessage
// vtable slot so a click on it opens a Windows dialog. Every other message
// goes to the game's own handler unchanged.
//
// All game addresses come from data/vf1_verified.json, where each one is
// recorded with the disassembly that confirms it. VF1 has no ASLR, so they
// are fixed.

#define WIN32_LEAN_AND_MEAN
// Modern (comctl32 v6) controls in this DLL's dialogs, through the manifest
// the linker embeds as resource 2 (see native/build.bat).
#define ISOLATION_AWARE_ENABLED 1
#include <windows.h>
#include <commctrl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <intrin.h>
#include <shlobj.h>

// ---------------------------------------------------------------- game ABI
struct ldwPoint { int x, y; };

typedef void *(__cdecl *NewFn)(size_t);
typedef void *(__cdecl *GetManagerFn)();
typedef void *(__thiscall *GetImageGridFn)(void *graphics, int image);
typedef void *(__thiscall *ButtonCtorFn)(void *self, int id, void *grid, ldwPoint pos, void *scene, bool flag);
typedef void (__thiscall *ButtonSetTextFn)(void *self, const char *text, unsigned c1, unsigned c2, unsigned c3, void *font);
typedef void (__thiscall *ButtonSetPosFn)(void *self, int x, int y);
typedef int (__thiscall *ButtonGetWidthFn)(void *self);
typedef void (__thiscall *AddControlFn)(void *scene, void *control);
typedef const char *(__thiscall *GetStringFn)(void *strings, int id);
typedef void (__thiscall *MoneyAdjustFn)(void *money, float amount, bool earned);
typedef bool (__thiscall *TrayAddItemFn)(void *tray, int item, int uses);
typedef int (__thiscall *GetUseCountFn)(void *inventory, int item);
typedef bool (__thiscall *HandleMessageFn)(void *scene, int message, int param);
typedef void (__thiscall *FoodAdjustFn)(void *food, int amount);
typedef void *(__cdecl *IslandEventsGetFn)();
typedef bool (__thiscall *FireEventFn)(void *events, void *scene);

static const NewFn GameNew = (NewFn)0x497B14;                       // operator new
static const GetManagerFn GraphicsGet = (GetManagerFn)0x44F7C0;     // theGraphicsManager::Get
static const GetManagerFn StringsGet = (GetManagerFn)0x450530;      // theStringManager::Get
static const GetImageGridFn GetImageGrid = (GetImageGridFn)0x44F5A0;
static const ButtonCtorFn ButtonCtor = (ButtonCtorFn)0x4019F0;
static const ButtonSetTextFn ButtonSetText = (ButtonSetTextFn)0x4015D0;
static const ButtonSetPosFn ButtonSetPos = (ButtonSetPosFn)0x401430;
static const ButtonGetWidthFn ButtonGetWidth = (ButtonGetWidthFn)0x401440;
static const AddControlFn AddControl = (AddControlFn)0x40C4B0;
static const GetStringFn GetString = (GetStringFn)0x44FD90;
static const MoneyAdjustFn MoneyAdjust = (MoneyAdjustFn)0x422740;
static const TrayAddItemFn TrayAddItem = (TrayAddItemFn)0x4973E0;
static const GetUseCountFn GetUseCount = (GetUseCountFn)0x4968E0;
static const FoodAdjustFn FoodAdjust = (FoodAdjustFn)0x4221B0;  // adds; clamps at 0 when lowering
static int *const Food = (int *)0x50C550;
static const IslandEventsGetFn IslandEventsGet = (IslandEventsGetFn)0x41B170;
static const FireEventFn FireEvent = (FireEventFn)0x41B360;  // random island event over a scene

static void *const Money = (void *)0x50C60C;         // +0: float money
static void *const ToolTray = (void *)0x8958E8;
static void *const Inventory = (void *)0x8957A0;
static unsigned *const ButtonTextColour = (unsigned *)0x4F1740;
// THE BANK INTEREST RATE.
// The game pays interest in CMoney's lazy interest routine (0x422830:
// money * 0.1 * whole game days, earned=true) and shows the projection
// (0x422810) and the bank dialog (0x415A7E) from the same double 0.1 at
// 0x4B4520; the dialog's "%" label loads the float 10.0 at 0x4B4528.
// NEITHER CONSTANT MAY BE WRITTEN: both are shared. 0x4B4528 is also an hour
// threshold in the day/night code (CNight, 0x491727 and 0x491773); v0.1.0 and
// v0.1.1 wrote it, which shifted day and night and never changed the interest
// actually paid. Instead the four instructions' memory operands are pointed at
// this DLL's own copies, which the cheat changes. With no rate set they hold
// the stock values, so the game behaves exactly as stock.
static double gInterestFraction = 0.1;   // replaces [0x4B4520] at three sites
static float gInterestPercent = 10.0f;   // replaces [0x4B4528] at the label
struct OperandSite { unsigned address; unsigned expected; void *replacement; };
static const OperandSite InterestSites[] = {
    { 0x422815, 0x4B4520, &gInterestFraction },  // projection: fmul qword [0x4B4520]
    { 0x422869, 0x4B4520, &gInterestFraction },  // payment: fmul qword [0x4B4520]
    { 0x415A80, 0x4B4520, &gInterestFraction },  // bank dialog: fld qword [0x4B4520]
    { 0x415887, 0x4B4528, &gInterestPercent },   // bank "%" label: fld dword [0x4B4528]
};

static void RedirectInterestOperands() {
    for (const OperandSite &s : InterestSites) {
        unsigned *operand = (unsigned *)s.address;
        if (*operand == (unsigned)s.replacement)
            continue;
        if (*operand != s.expected)
            return;  // not the bytes we verified: leave the game as it is
    }
    for (const OperandSite &s : InterestSites) {
        unsigned *operand = (unsigned *)s.address;
        DWORD old;
        if (VirtualProtect(operand, 4, PAGE_EXECUTE_READWRITE, &old)) {
            *operand = (unsigned)s.replacement;
            VirtualProtect(operand, 4, old, &old);
            FlushInstructionCache(GetCurrentProcess(), operand, 4);
        }
    }
}
static const unsigned char *const ItemTable = (const unsigned char *)0x4FE190;  // 32-byte records, item 1 at +0x20

static unsigned *const StoreVtable = (unsigned *)0x4B7220;
static const int StoreHandleMessageSlot = 3;
static const int DoneButtonImage = 0x26;
static const int DoneButtonX = 10, DoneButtonY = 0x236;
static const int UpgradesButtonId = 0x5646;  // 'VF', not used by the store
static const int MessageButtonClicked = 8;

static HandleMessageFn OriginalHandleMessage;
static HINSTANCE Module;

// ---------------------------------------------------------------- items
struct ItemRecord { int id, unknown1, unknown2, price, shortDesc, longDesc, flag, upgrade; };

static const ItemRecord *Item(int id) {
    return (const ItemRecord *)(ItemTable + id * 32);
}

static float CurrentMoney() { return *(float *)Money; }

// ---------------------------------------------------------------- dialogs
// Dialog templates are built in memory so the DLL needs no resource script.
class Template {
    WORD buf[4096];
    int n;
    void Str(const wchar_t *s) { do buf[n++] = *s; while (*s++); }
public:
    DLGTEMPLATE *Begin(const wchar_t *title, int w, int h, int count) {
        n = 0;
        DLGTEMPLATE *t = (DLGTEMPLATE *)buf;
        t->style = DS_MODALFRAME | DS_CENTER | DS_SETFONT | WS_POPUP | WS_CAPTION | WS_SYSMENU;
        t->dwExtendedStyle = 0;
        t->cdit = (WORD)count;
        t->x = 0; t->y = 0; t->cx = (short)w; t->cy = (short)h;
        n = sizeof(DLGTEMPLATE) / 2;
        buf[n++] = 0; buf[n++] = 0;  // no menu, default class
        Str(title);
        buf[n++] = 9;                // point size
        Str(L"Segoe UI");
        return t;
    }
    void Item(WORD cls, DWORD style, int x, int y, int w, int h, int id, const wchar_t *text) {
        // DLGITEMTEMPLATE must be DWORD aligned (n counts WORDs).
        if (n % 2) buf[n++] = 0;
        DLGITEMTEMPLATE *it = (DLGITEMTEMPLATE *)(buf + n);
        it->style = style | WS_CHILD | WS_VISIBLE;
        it->dwExtendedStyle = 0;
        it->x = (short)x; it->y = (short)y; it->cx = (short)w; it->cy = (short)h;
        it->id = (WORD)id;
        n += sizeof(DLGITEMTEMPLATE) / 2;
        buf[n++] = 0xFFFF; buf[n++] = cls;
        Str(text);
        buf[n++] = 0;  // no creation data
    }
    DLGTEMPLATE *Get() { return (DLGTEMPLATE *)buf; }
};

enum { BUTTON = 0x80, EDIT = 0x81, STATIC = 0x82, LISTBOX = 0x83 };

static HWND GameWindow() { return GetActiveWindow(); }

// While a patcher dialog is open the game leaves fullscreen (VF1's ldw.ini
// defaults to FullScreen=1), so the dialog cannot end up hidden behind it; the
// exact fullscreen mode is restored afterwards. Uses the game's own SDL2.dll.
class LeaveFullscreen {
    typedef void *(__cdecl *GetWindowFn)();
    typedef unsigned (__cdecl *GetFlagsFn)(void *);
    typedef int (__cdecl *SetFullscreenFn)(void *, unsigned);
    void *window;
    unsigned mode;
    SetFullscreenFn setFullscreen;
public:
    LeaveFullscreen() : window(0), mode(0), setFullscreen(0) {
        HMODULE sdl = GetModuleHandleW(L"SDL2.dll");
        if (!sdl)
            return;
        GetWindowFn focus = (GetWindowFn)GetProcAddress(sdl, "SDL_GetKeyboardFocus");
        GetWindowFn current = (GetWindowFn)GetProcAddress(sdl, "SDL_GL_GetCurrentWindow");
        GetFlagsFn flags = (GetFlagsFn)GetProcAddress(sdl, "SDL_GetWindowFlags");
        setFullscreen = (SetFullscreenFn)GetProcAddress(sdl, "SDL_SetWindowFullscreen");
        if (!flags || !setFullscreen)
            return;
        void *w = focus ? focus() : 0;
        if (!w && current)
            w = current();
        if (!w)
            return;
        const unsigned SDL_WINDOW_FULLSCREEN_DESKTOP = 0x1001, SDL_WINDOW_FULLSCREEN = 0x1;
        unsigned f = flags(w);
        if (f & SDL_WINDOW_FULLSCREEN) {
            mode = f & SDL_WINDOW_FULLSCREEN_DESKTOP;
            if (setFullscreen(w, 0) == 0)
                window = w;
        }
    }
    ~LeaveFullscreen() {
        if (window)
            setFullscreen(window, mode);
    }
};

static void Message(HWND owner, const wchar_t *text) {
    MessageBoxW(owner, text, L"Virtual Families 1 Patcher", MB_OK | MB_ICONINFORMATION);
}

// ---- Cheats
enum { ID_MONEY_NOW = 100, ID_ADD1K, ID_ADD10K, ID_ADD100K, ID_SET_EDIT, ID_SET, ID_RATE_EDIT, ID_RATE,
       ID_FOOD_NOW, ID_FOOD100, ID_FOOD1000, ID_FOOD_EDIT, ID_FOOD_SET, ID_MONEY0, ID_ADD100, ID_ADDMAX,
       ID_FOOD0, ID_FOOD10K, ID_FOODMAX };
// VF1 has no maximum for money or food (CMoney::Adjust and CFoodStore::Adjust
// never clamp upward); these are the largest amounts the HUD still shows whole.
static const float kMaxMoney = 99999999.f;
static const int kMaxFood = 99999;

static void RefreshCheats(HWND dlg) {
    wchar_t s[128];
    swprintf(s, 128, L"Money now: $%.0f        Interest rate now: %.1f%%", CurrentMoney(), gInterestPercent);
    SetDlgItemTextW(dlg, ID_MONEY_NOW, s);
    swprintf(s, 128, L"Food now: %d", *Food);
    SetDlgItemTextW(dlg, ID_FOOD_NOW, s);
}

// ---- settings.ini beside this DLL (the game does not save these)
static wchar_t SettingsPath[MAX_PATH];

static void InitSettingsPath() {
    if (SettingsPath[0])
        return;
    GetModuleFileNameW(Module, SettingsPath, MAX_PATH);
    wchar_t *slash = wcsrchr(SettingsPath, L'\\');
    if (slash)
        wcscpy_s(slash + 1, MAX_PATH - (slash + 1 - SettingsPath), L"settings.ini");
}

static float ReadSetting(const wchar_t *key, float fallback) {
    wchar_t s[64];
    GetPrivateProfileStringW(L"Cheats", key, L"", s, 64, SettingsPath);
    return s[0] ? (float)_wtof(s) : fallback;
}

static void WriteSetting(const wchar_t *key, float value) {
    InitSettingsPath();
    wchar_t s[64];
    swprintf(s, 64, L"%g", value);
    WritePrivateProfileStringW(L"Cheats", key, s, SettingsPath);
}

static void ApplyInterestRate(float percent) {
    RedirectInterestOperands();
    gInterestFraction = percent / 100.0;
    gInterestPercent = percent;
}

static void CheatInterestChanged(float percent);  // features.inc
static void SetInterestRate(float percent) {
    WriteSetting(L"InterestRate", percent);
    CheatInterestChanged(percent);
}

static INT_PTR CALLBACK CheatsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG:
        RefreshCheats(dlg);
        return TRUE;
    case WM_COMMAND: {
        int id = LOWORD(wp);
        float add = id == ID_ADD100 ? 100.f : id == ID_ADD10K ? 10000.f : 0.f;
        if (id == ID_MONEY0 || id == ID_ADDMAX) {
            MoneyAdjust(Money, (id == ID_ADDMAX ? kMaxMoney : 0.f) - CurrentMoney(), false);
            RefreshCheats(dlg);
        } else if (id == ID_FOOD0 || id == ID_FOODMAX) {
            FoodAdjust(Food, (id == ID_FOODMAX ? kMaxFood : 0) - *Food);
            RefreshCheats(dlg);
        } else if (id == ID_FOOD100 || id == ID_FOOD10K) {
            FoodAdjust(Food, id == ID_FOOD100 ? 100 : 10000);
            RefreshCheats(dlg);
        } else if (add) {
            MoneyAdjust(Money, add, false);  // not "earned": no money achievements
            RefreshCheats(dlg);
        } else if (id == ID_SET) {
            wchar_t s[64];
            GetDlgItemTextW(dlg, ID_SET_EDIT, s, 64);
            float target = (float)_wtof(s);
            if (target < 0 || target > 1e9f) { Message(dlg, L"Enter an amount from 0 to 1,000,000,000."); break; }
            MoneyAdjust(Money, target - CurrentMoney(), false);
            RefreshCheats(dlg);
        } else if (id == ID_RATE) {
            wchar_t s[64];
            GetDlgItemTextW(dlg, ID_RATE_EDIT, s, 64);
            float rate = (float)_wtof(s);
            if (rate < 0 || rate > 100) { Message(dlg, L"Enter a rate from 0 to 100 percent."); break; }
            SetInterestRate(rate);
            RefreshCheats(dlg);
        } else if (id == ID_FOOD_SET) {
            wchar_t s[64];
            GetDlgItemTextW(dlg, ID_FOOD_EDIT, s, 64);
            int target = _wtoi(s);
            if (target < 0 || target > 1000000) { Message(dlg, L"Enter an amount of food from 0 to 1,000,000."); break; }
            FoodAdjust(Food, target - *Food);
            RefreshCheats(dlg);
        } else if (id == IDCANCEL || id == IDOK) {
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

static void ShowCheats(HWND owner) {
    static Template t;
    t.Begin(L"Cheat Upgrades", 260, 200, 20);
    t.Item(STATIC, SS_LEFT, 10, 8, 240, 12, ID_MONEY_NOW, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 26, 56, 16, ID_MONEY0, L"No Money");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 70, 26, 56, 16, ID_ADD100, L"+ 100");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 130, 26, 62, 16, ID_ADD10K, L"+ 10,000");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 196, 26, 53, 16, ID_ADDMAX, L"Max");
    t.Item(STATIC, SS_LEFT, 10, 52, 80, 12, -1, L"Set money to $");
    t.Item(EDIT, ES_LEFT | ES_AUTOHSCROLL | WS_BORDER | WS_TABSTOP, 92, 50, 75, 14, ID_SET_EDIT, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 174, 49, 75, 16, ID_SET, L"Set");
    t.Item(STATIC, SS_LEFT, 10, 78, 80, 12, -1, L"Interest rate %");
    t.Item(EDIT, ES_LEFT | ES_AUTOHSCROLL | WS_BORDER | WS_TABSTOP, 92, 76, 75, 14, ID_RATE_EDIT, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 174, 75, 75, 16, ID_RATE, L"Set rate");
    t.Item(STATIC, SS_LEFT, 10, 104, 240, 12, ID_FOOD_NOW, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 120, 56, 16, ID_FOOD0, L"No Food");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 70, 120, 56, 16, ID_FOOD100, L"+ 100");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 130, 120, 62, 16, ID_FOOD10K, L"+ 10,000");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 196, 120, 53, 16, ID_FOODMAX, L"Max");
    t.Item(STATIC, SS_LEFT, 10, 146, 80, 12, -1, L"Set food to");
    t.Item(EDIT, ES_LEFT | ES_AUTOHSCROLL | ES_NUMBER | WS_BORDER | WS_TABSTOP, 92, 144, 75, 14, ID_FOOD_EDIT, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 174, 143, 75, 16, ID_FOOD_SET, L"Set");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 174, 176, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, CheatsProc, 0);
}

// ---- Villager cheats
// Villager i (0-29) is at VillagerManager + 0x14640 + i * 0x145FC
// (CVillagerManager::GetVillager 0x489900). Its CVillagerState is at +0x2AD4
// (every CVillagerState::SetSymptom caller), with VF2's layout, confirmed
// live against the Detail screen: health +0x0C, energy +0x34 and happiness
// +0x38 (100 best), and hunger +0x40 (1-100, 100 STARVING: the Detail
// screen's Fed bar is 100 - hunger; writing 100 emptied it in a live test,
// 2026-10-10); seven symptom flags at
// +0x5C and their end times at +0x64. The name is at +0x2A44; a villager who
// is present has the byte at +0x13574 set and health above 0
// (CVillagerManager::Population 0x48AC90).
static unsigned char *const VillagerManager = (unsigned char *)0x5B8898;
static const int VillagerSlots = 30;

static unsigned char *Villager(int i) { return VillagerManager + 0x14640 + i * 0x145FC; }
static bool VillagerPresent(int i) {
    unsigned char *v = Villager(i);
    return v[0x13574] != 0 && *(int *)(v + 0x2AE0) > 0;
}
static int *Stat(int i, int offset) { return (int *)(Villager(i) + 0x2AD4 + offset); }

enum { STAT_HEALTH = 0x0C, STAT_ENERGY = 0x34, STAT_HAPPINESS = 0x38, STAT_HUNGER = 0x40 };
static int Fed(int i) { return 100 - *Stat(i, STAT_HUNGER); }
enum { ID_VC_LIST = 400, ID_VC_HEALTH, ID_VC_CURE, ID_VC_HAPPY, ID_VC_ENERGY, ID_VC_FED, ID_VC_ALL,
       ID_VC_HEAD, ID_VC_BODY, ID_VC_LOOKS, ID_VC_RANDOM_LOOKS, ID_VC_PROMOTE, ID_VC_CAREER,
       ID_VC_BOARD, ID_VC_DESENS, ID_VC_LEARN, ID_VC_PSYCHO, ID_VC_RUNNING, ID_VC_AGE18 };
static const wchar_t *ApplyVillagerUpgrade(int id, int slot);  // villager_upgrades.inc

static void CureVillager(int i) {
    unsigned char *state = Villager(i) + 0x2AD4;
    for (int s = 0; s < 7; ++s) {
        state[0x5C + s] = 0;
        *(unsigned *)(state + 0x64 + s * 4) = 0;
    }
}

// Appearance: VF1 has no separate clothing or hair field. The head row
// (+0x2A60: face and hair) and the body row (+0x2A64: clothes) are each one
// of 50 sprite-sheet rows, 0-49 (CVillager::Init 0x485108..0x4851A8; drawn at
// 0x48B944 / 0x48B5A2), and every row fits every age.
static const int AppearanceRows = 50;
static int *Head(int i) { return (int *)(Villager(i) + 0x2A60); }
static int *Body(int i) { return (int *)(Villager(i) + 0x2A64); }
static void SyncTreeLook(int slot);  // family.inc
typedef int (__cdecl *RandomFn)(int n);
static const RandomFn GetRandom = (RandomFn)0x403650;  // ldwGameState::GetRandom

// Careers (CVillagerSkills at villager +0x2B6C: id, level, experience, salary).
// A child has career id -1. Both calls are the ones the game's own island events
// make: CEventProfessionalCareerTraining::ImpactGame (0x419650) calls
// AdvanceCareer(villager, giveMoney=false, forcePromotion=true) and
// CEventCareerChangeCouncelor::ImpactGame (0x419A20) calls ResetCareer().
typedef void (__thiscall *AdvanceCareerFn)(void *skills, void *villager, bool giveMoney, bool force);
typedef void (__thiscall *ResetCareerFn)(void *skills);
static bool HasCareer(int i) { return *(int *)(Villager(i) + 0x2B6C) != -1; }
static void PromoteVillager(int i) {
    ((AdvanceCareerFn)0x48F590)(Villager(i) + 0x2B6C, Villager(i), false, true);
}
static void ChangeCareer(int i) { ((ResetCareerFn)0x48F020)(Villager(i) + 0x2B6C); }

static void ApplyVillagerCheat(int i, int id) {
    if (id == ID_VC_HEALTH || id == ID_VC_ALL) *Stat(i, STAT_HEALTH) = 100;
    if (id == ID_VC_CURE || id == ID_VC_ALL) CureVillager(i);
    if (id == ID_VC_HAPPY || id == ID_VC_ALL) *Stat(i, STAT_HAPPINESS) = 100;
    if (id == ID_VC_ENERGY || id == ID_VC_ALL) *Stat(i, STAT_ENERGY) = 100;
    if (id == ID_VC_FED || id == ID_VC_ALL) *Stat(i, STAT_HUNGER) = 1;  // fully fed (SetHunger's minimum)
}

static void FillVillagerList(HWND dlg) {
    HWND list = GetDlgItem(dlg, ID_VC_LIST);
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    int row = (int)SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)L"Everyone");
    SendMessageW(list, LB_SETITEMDATA, row, -1);
    for (int i = 0; i < VillagerSlots; ++i) {
        if (!VillagerPresent(i))
            continue;
        wchar_t line[128];
        swprintf(line, 128, L"%.40hs\tHealth %d  Happy %d  Fed %d  Energy %d  Head %d  Body %d",
                 (const char *)(Villager(i) + 0x2A44), *Stat(i, STAT_HEALTH), *Stat(i, STAT_HAPPINESS),
                 Fed(i), *Stat(i, STAT_ENERGY), *Head(i), *Body(i));
        row = (int)SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
        SendMessageW(list, LB_SETITEMDATA, row, i);
    }
    SendMessageW(list, LB_SETCURSEL, 0, 0);
}

static INT_PTR CALLBACK VillagerCheatsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        int stop = 90;
        SendMessageW(GetDlgItem(dlg, ID_VC_LIST), LB_SETTABSTOPS, 1, (LPARAM)&stop);
        FillVillagerList(dlg);
        return TRUE;
    }
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (id == ID_VC_LIST && HIWORD(wp) == LBN_SELCHANGE) {
            HWND list = GetDlgItem(dlg, ID_VC_LIST);
            int who = (int)SendMessageW(list, LB_GETITEMDATA, SendMessageW(list, LB_GETCURSEL, 0, 0), 0);
            if (who >= 0 && who < VillagerSlots) {
                SetDlgItemInt(dlg, ID_VC_HEAD, *Head(who), FALSE);
                SetDlgItemInt(dlg, ID_VC_BODY, *Body(who), FALSE);
            }
        } else if (id == ID_VC_LOOKS || id == ID_VC_RANDOM_LOOKS) {
            HWND list = GetDlgItem(dlg, ID_VC_LIST);
            int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            int who = sel < 0 ? -1 : (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
            BOOL okHead, okBody;
            int head = (int)GetDlgItemInt(dlg, ID_VC_HEAD, &okHead, FALSE);
            int body = (int)GetDlgItemInt(dlg, ID_VC_BODY, &okBody, FALSE);
            if (id == ID_VC_LOOKS && (!okHead || !okBody || head >= AppearanceRows || body >= AppearanceRows)) {
                Message(dlg, L"Head and body are each a number from 0 to 49.");
                return TRUE;
            }
            for (int i = 0; i < VillagerSlots; ++i) {
                if (!VillagerPresent(i) || (who >= 0 && who != i))
                    continue;
                *Head(i) = id == ID_VC_LOOKS ? head : GetRandom(AppearanceRows);
                *Body(i) = id == ID_VC_LOOKS ? body : GetRandom(AppearanceRows);
                SyncTreeLook(i);
            }
            FillVillagerList(dlg);
            if (sel > 0) SendMessageW(list, LB_SETCURSEL, sel, 0);
        } else if (id == ID_VC_PROMOTE || id == ID_VC_CAREER) {
            HWND list = GetDlgItem(dlg, ID_VC_LIST);
            int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            int who = sel < 0 ? -1 : (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
            int done = 0;
            for (int i = 0; i < VillagerSlots; ++i) {
                if (!VillagerPresent(i) || (who >= 0 && who != i) || !HasCareer(i))
                    continue;
                if (id == ID_VC_PROMOTE) PromoteVillager(i); else ChangeCareer(i);
                ++done;
            }
            if (!done) Message(dlg, L"Only adults with a career can do that.");
            FillVillagerList(dlg);
            if (sel > 0) SendMessageW(list, LB_SETCURSEL, sel, 0);
        } else if (id >= ID_VC_BOARD && id <= ID_VC_AGE18) {
            HWND list = GetDlgItem(dlg, ID_VC_LIST);
            int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            int who = sel < 0 ? -1 : (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
            if (id == ID_VC_AGE18 && who < 0) {
                Message(dlg, L"Pick one villager: Set Age to 18 only changes the selected villager.");
                return TRUE;
            }
            int done = 0;
            const wchar_t *why = 0;
            for (int i = 0; i < VillagerSlots; ++i) {
                if (!VillagerPresent(i) || (who >= 0 && who != i))
                    continue;
                const wchar_t *reason = ApplyVillagerUpgrade(id, i);
                if (reason) why = reason; else ++done;
            }
            if (!done && why) Message(dlg, why);
            FillVillagerList(dlg);
            if (sel > 0) SendMessageW(list, LB_SETCURSEL, sel, 0);
        } else if (id >= ID_VC_HEALTH && id <= ID_VC_ALL) {
            HWND list = GetDlgItem(dlg, ID_VC_LIST);
            int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            int who = sel < 0 ? -1 : (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
            for (int i = 0; i < VillagerSlots; ++i)
                if (VillagerPresent(i) && (who < 0 || who == i))
                    ApplyVillagerCheat(i, id);
            FillVillagerList(dlg);
            if (sel > 0) SendMessageW(list, LB_SETCURSEL, sel, 0);
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

static void ShowVillagerCheats(HWND owner) {
    static Template t;
    t.Begin(L"Villager Cheats", 340, 322, 24);
    t.Item(LISTBOX, LBS_NOTIFY | LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 10, 10, 320, 110, ID_VC_LIST, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 128, 90, 18, ID_VC_HEALTH, L"Max health");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 105, 128, 90, 18, ID_VC_CURE, L"Cure illnesses");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 200, 128, 90, 18, ID_VC_HAPPY, L"Max happiness");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 152, 90, 18, ID_VC_ENERGY, L"Max energy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 105, 152, 90, 18, ID_VC_FED, L"Fill up (Fed)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 200, 152, 90, 18, ID_VC_ALL, L"All of these");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 176, 150, 18, ID_VC_PROMOTE, L"Instant job promotion");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 170, 176, 150, 18, ID_VC_CAREER, L"Career Change (new career)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 200, 104, 18, ID_VC_BOARD, L"Boarding School");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 118, 200, 104, 18, ID_VC_DESENS, L"Systematic Desens.");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 226, 200, 104, 18, ID_VC_LEARN, L"Higher Learning");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 224, 104, 18, ID_VC_PSYCHO, L"Psychotherapy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 118, 224, 104, 18, ID_VC_RUNNING, L"Add Running Like");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 226, 224, 104, 18, ID_VC_AGE18, L"Set Age to 18");
    t.Item(BUTTON, BS_GROUPBOX, 6, 248, 328, 40, -1, L"Change Appearance (hairstyle and face, clothes)");
    t.Item(STATIC, SS_LEFT, 14, 266, 30, 12, -1, L"Head:");
    t.Item(EDIT, ES_LEFT | ES_NUMBER | WS_BORDER | WS_TABSTOP, 44, 264, 26, 14, ID_VC_HEAD, L"");
    t.Item(STATIC, SS_LEFT, 78, 266, 30, 12, -1, L"Body:");
    t.Item(EDIT, ES_LEFT | ES_NUMBER | WS_BORDER | WS_TABSTOP, 108, 264, 26, 14, ID_VC_BODY, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 142, 263, 84, 16, ID_VC_LOOKS, L"Change (0-49)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 232, 263, 94, 16, ID_VC_RANDOM_LOOKS, L"Random look");
    t.Item(STATIC, SS_LEFT, 10, 300, 220, 12, -1, L"Pick Everyone to change everybody at once.");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 255, 296, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, VillagerCheatsProc, 0);
}

// ---- Flea Market
enum { ID_FM_LIST = 200, ID_FM_BUY, ID_FM_FREE, ID_FM_MONEY };

static bool FleaMarketItem(int id) {
    // Tray items: drinks, candies, medicines, care items, repair kits,
    // magazines, movies, bottles, books, kits and pets. Not groceries
    // (4-11, bought for the kitchen) and not the two toys (18-19), which the
    // store remaps to other ids.
    return (id >= 12 && id <= 17) || (id >= 20 && id <= 63);
}

static void RefreshFleaMoney(HWND dlg) {
    wchar_t s[64];
    swprintf(s, 64, L"Money: $%.0f", CurrentMoney());
    SetDlgItemTextW(dlg, ID_FM_MONEY, s);
}

static void BuyItem(HWND dlg, bool free) {
    HWND list = GetDlgItem(dlg, ID_FM_LIST);
    int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
    if (sel < 0) { Message(dlg, L"Pick an item first."); return; }
    int id = (int)SendMessageW(list, LB_GETITEMDATA, sel, 0);
    int price = Item(id)->price;
    if (!free && CurrentMoney() < price) { Message(dlg, L"You don't have enough money for that."); return; }
    // Same calls the store makes when you buy (theStoreScene::Buy 0x449A70),
    // except the store's limited stock is not used up.
    if (!TrayAddItem(ToolTray, id, GetUseCount(Inventory, id))) {
        Message(dlg, L"Your item tray is full. Use or sell something first.");
        return;
    }
    if (!free)
        MoneyAdjust(Money, (float)-price, false);
    RefreshFleaMoney(dlg);
}

static INT_PTR CALLBACK FleaProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        HWND list = GetDlgItem(dlg, ID_FM_LIST);
        int stop = 180;  // dialog units: the price column
        SendMessageW(list, LB_SETTABSTOPS, 1, (LPARAM)&stop);
        void *strings = StringsGet();
        for (int id = 1; id <= 80; ++id) {
            if (!FleaMarketItem(id))
                continue;
            const ItemRecord *r = Item(id);
            const char *name = GetString(strings, r->shortDesc);
            wchar_t line[160];
            swprintf(line, 160, L"%hs\t$%d", name ? name : "?", r->price);
            int row = (int)SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
            SendMessageW(list, LB_SETITEMDATA, row, id);
        }
        RefreshFleaMoney(dlg);
        return TRUE;
    }
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_FM_BUY: BuyItem(dlg, false); break;
        case ID_FM_FREE: BuyItem(dlg, true); break;
        case ID_FM_LIST: if (HIWORD(wp) == LBN_DBLCLK) BuyItem(dlg, false); break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); break;
        }
        return TRUE;
    case WM_CLOSE:
        EndDialog(dlg, 0);
        return TRUE;
    }
    return FALSE;
}

static void ShowFleaMarket(HWND owner) {
    static Template t;
    t.Begin(L"Flea Market", 280, 250, 5);
    t.Item(STATIC, SS_LEFT, 10, 8, 200, 12, ID_FM_MONEY, L"");
    t.Item(LISTBOX, LBS_NOTIFY | LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 10, 24, 260, 190, ID_FM_LIST, L"");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 10, 224, 80, 16, ID_FM_BUY, L"Buy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 96, 224, 80, 16, ID_FM_FREE, L"Get for free");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 190, 224, 80, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, FleaProc, 0);
}

// ---- Upgrades menu
enum { ID_UP_CHEATS = 300, ID_UP_FLEA, ID_UP_DICE, ID_UP_VILLAGERS, ID_UP_STORE, ID_UP_HOUSE,
       ID_UP_PURCHASES, ID_UP_TIME, ID_UP_COUNTERS, ID_UP_FAMILY, ID_UP_ACH };
static void ShowAchievements(HWND owner);
static int AchievementsUnlocked();
static const int kAchievementTotal = 8;  // ACH_COUNT, patcher_achievements.inc
static void ShowFamily(HWND owner);
static int gFamilyAction;
static void ShowStoreCheats(HWND owner);
static void ShowHouse(HWND owner);
static void ShowPurchases(HWND owner);
static void ShowTime(HWND owner);
static int GenerationNumber();
static int OldestEverAge();
static const int RollTheDicePrice = 500;
static bool RollPending;

static bool SettingOn(const wchar_t *key, bool fallback);

static INT_PTR CALLBACK UpgradesProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG:
        // Each page is a patch setting (Patches section of settings.ini,
        // written by the patcher); a page that is switched off is greyed out.
        EnableWindow(GetDlgItem(dlg, ID_UP_CHEATS), SettingOn(L"CheatUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_VILLAGERS), SettingOn(L"CheatUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_FLEA), SettingOn(L"FleaMarket", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_DICE), SettingOn(L"RollTheDice", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_STORE), SettingOn(L"CheatUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_HOUSE), SettingOn(L"CheatUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_TIME), SettingOn(L"CheatUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_PURCHASES), SettingOn(L"SpecialUpgrades", true));
        EnableWindow(GetDlgItem(dlg, ID_UP_FAMILY), SettingOn(L"CheatUpgrades", true));
        {
            wchar_t s[96];
            swprintf(s, 96, L"Generation: %d     Oldest Villager: %d     Achievements: %d/%d", GenerationNumber(),
                     OldestEverAge(), AchievementsUnlocked(), kAchievementTotal);
            SetDlgItemTextW(dlg, ID_UP_COUNTERS, s);
        }
        return TRUE;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_UP_CHEATS: ShowCheats(dlg); break;
        case ID_UP_FLEA: ShowFleaMarket(dlg); break;
        case ID_UP_VILLAGERS: ShowVillagerCheats(dlg); break;
        case ID_UP_STORE: ShowStoreCheats(dlg); break;
        case ID_UP_HOUSE: ShowHouse(dlg); break;
        case ID_UP_PURCHASES: ShowPurchases(dlg); break;
        case ID_UP_TIME: ShowTime(dlg); break;
        case ID_UP_ACH: ShowAchievements(dlg); break;
        case ID_UP_FAMILY:
            ShowFamily(dlg);
            if (gFamilyAction) EndDialog(dlg, 0);  // Evict / Adopt New Person leave the store
            break;
        case ID_UP_DICE:
            if (CurrentMoney() < RollTheDicePrice) {
                Message(dlg, L"Roll the Dice costs $500, and you don't have enough money.");
                break;
            }
            // The event shows the game's own dialog, so this one closes first.
            RollPending = true;
            EndDialog(dlg, 0);
            break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); break;
        }
        return TRUE;
    case WM_CLOSE:
        EndDialog(dlg, 0);
        return TRUE;
    }
    return FALSE;
}

static void ShowUpgrades() {
    static Template t;
    t.Begin(L"Upgrades Menu", 220, 282, 12);
    t.Item(STATIC, SS_LEFT, 10, 8, 200, 12, ID_UP_COUNTERS, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 24, 200, 18, ID_UP_CHEATS, L"Cheat Upgrades: money, food, interest...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 46, 200, 18, ID_UP_VILLAGERS, L"Villager Cheats: health, cures...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 68, 200, 18, ID_UP_STORE, L"Store, Achievement and Collection Cheats...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 90, 200, 18, ID_UP_HOUSE, L"House and Yard: trash, weeds, cleaning...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 112, 200, 18, ID_UP_TIME, L"Time Controls: pause, speed, time warp...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 134, 200, 18, ID_UP_PURCHASES, L"Special Upgrades: Food Club, Maid, Lucky Rock...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 156, 200, 18, ID_UP_FAMILY, L"Family: marriage, babies, adoption...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 178, 200, 18, ID_UP_FLEA, L"Flea Market...");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 200, 200, 18, ID_UP_DICE, L"Roll the Dice ($500): an island event now");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 222, 200, 18, ID_UP_ACH, L"Patcher Achievements...");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 135, 258, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), GameWindow(), UpgradesProc, 0);
}

// ---------------------------------------------------------------- vanilla bug fixes
// FIX: A NEW FAMILY IS LOST IF THE GAME IS CLOSED WITHOUT QUITTING.
// The stock game saves when the intro story starts (CStoryScene::Activate
// calls theGameState::SaveCurrentGame), which is BEFORE anyone is adopted, and
// not again until the player quits through the menu. Those saves are an empty
// game (live 2026-10-10: 108,718 of 111,000 bytes zero, no villager), so a game
// closed any other way reloads with nobody in it and shows "All of your little
// family members died". The same gap follows Start Over and Next Generation,
// which also adopt through CAdoptionScene.
// The fix saves right after the Adopt button has been handled
// (CAdoptionScene::HandleMessage, message 8 / button 1: the villager is marked
// present, named and paid by then), the way the game's own dialogs call
// SaveCurrentGame from their message handlers.
typedef void *(__cdecl *GameStateGetFn)();
typedef bool (__thiscall *SaveCurrentGameFn)(void *state);
static const GameStateGetFn GameStateGet = (GameStateGetFn)0x423660;
static const SaveCurrentGameFn SaveCurrentGame = (SaveCurrentGameFn)0x4238E0;
static unsigned *const AdoptionVtable = (unsigned *)0x4B6BD4;
static const int AdoptButtonId = 1;
static HandleMessageFn OriginalAdoptionHandleMessage;

static bool __fastcall AdoptionHandleMessage(void *scene, void *, int message, int param) {
    bool result = OriginalAdoptionHandleMessage(scene, message, param);
    if (message == MessageButtonClicked && param == AdoptButtonId)
        SaveCurrentGame(GameStateGet());
    return result;
}

static bool HookVtableSlot(unsigned *slot, void *replacement, unsigned *original) {
    if (*slot == (unsigned)replacement)
        return true;
    *original = *slot;
    DWORD old;
    if (!VirtualProtect(slot, 4, PAGE_READWRITE, &old))
        return false;
    *slot = (unsigned)replacement;
    VirtualProtect(slot, 4, old, &old);
    return true;
}

static bool SettingOn(const wchar_t *key, bool fallback) {
    InitSettingsPath();
    return GetPrivateProfileIntW(L"Patches", key, fallback ? 1 : 0, SettingsPath) != 0;
}

#include "features.inc"
#include "pages.inc"
#include "family.inc"
#include "family_page.inc"
#include "villager_upgrades.inc"
#include "patcher_achievements.inc"

// ---------------------------------------------------------------- hooks
static bool __fastcall StoreHandleMessage(void *scene, void *, int message, int param) {
    if (message == MessageButtonClicked && param == UpgradesButtonId) {
        RollPending = false;
        gFamilyAction = 0;
        {
            LeaveFullscreen windowed;
            ShowUpgrades();
        }
        if (RollPending) {
            RollPending = false;
            MoneyAdjust(Money, (float)-RollTheDicePrice, false);
            if (!FireEvent(IslandEventsGet(), scene)) {
                MoneyAdjust(Money, (float)RollTheDicePrice, false);
                Message(GameWindow(), L"No island event can happen right now, so the dice weren't rolled. Your $500 was refunded.");
            }
        }
        if (gFamilyAction) {
            OpenNewFamilyAdoption(scene, gFamilyAction);
            gFamilyAction = 0;
        }
        return false;
    }
    return OriginalHandleMessage(scene, message, param);
}

static void HookStoreHandleMessage() {
    unsigned *slot = StoreVtable + StoreHandleMessageSlot;
    if (*slot == (unsigned)&StoreHandleMessage)
        return;
    OriginalHandleMessage = (HandleMessageFn)*slot;
    DWORD old;
    if (VirtualProtect(slot, 4, PAGE_READWRITE, &old)) {
        *slot = (unsigned)&StoreHandleMessage;
        VirtualProtect(slot, 4, old, &old);
    }
}

static void AddUpgradesButton(void *scene) {
    void *button = GameNew(0x14);
    if (!button)
        return;
    void *grid = GetImageGrid(GraphicsGet(), DoneButtonImage);
    ldwPoint pos = { DoneButtonX, DoneButtonY };
    ButtonCtor(button, UpgradesButtonId, grid, pos, scene, false);
    void *font = *(void **)StringsGet();
    unsigned colour = *ButtonTextColour;
    ButtonSetText(button, "Upgrades", colour, colour, colour, font);
    int width = ButtonGetWidth(button);
    ButtonSetPos(button, DoneButtonX + width + 12, DoneButtonY);
    AddControl(scene, button);
}

// Called once per frame, from theGame::GameUpdate's vtable slot, before the
// real GameUpdate runs (ldwGame::Run 0x402CC0 calls GameUpdate then GameDraw
// each pass of its main loop). Periodic features hang off this.
extern "C" __declspec(dllexport) void __cdecl VF1Fun_Tick() {
    FeaturesTick();
}

// Called once at startup, from theGame::Init's vtable slot, before the real
// Init runs. Only plain memory writes here: the game is not set up yet.
extern "C" __declspec(dllexport) void __cdecl VF1Fun_Startup() {
    InitSettingsPath();
    float rate = ReadSetting(L"InterestRate", -1.f);
    if (rate >= 0 && rate <= 100)
        ApplyInterestRate(rate);
    InstallFeatureHooks();
    if (SettingOn(L"CheatUpgrades", true))
        InstallFamilyHooks();
    if (rate >= 0 && rate <= 100)
        gCheatInterestPercent = rate;
    ApplyEffectiveInterest();
    if (SettingOn(L"FixVanillaGameBugs", true)) {
        HookVtableSlot(AdoptionVtable + StoreHandleMessageSlot, (void *)&AdoptionHandleMessage,
                       (unsigned *)&OriginalAdoptionHandleMessage);
        InstallPowerFailureFix();
    }
}

extern "C" __declspec(dllexport) void __cdecl VF1Fun_StoreCreated(void *scene) {
    HookStoreHandleMessage();
    AddUpgradesButton(scene);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        Module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
