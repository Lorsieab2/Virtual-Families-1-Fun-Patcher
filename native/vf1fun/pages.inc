// pages.inc -- the Upgrades menu's newer pages; included after features.inc.

static int GenerationNumber() { return *(int *)0x5AB908; }     // CFamilyTree+0, starts at 1
static int OldestEverAge() { return *(int *)0x50C580; }        // CGameStats+0x20, years

// ---- Store, achievement and collection cheats (VF2 wording)
enum { ID_SC_STATUS = 500, ID_SC_X2, ID_SC_X5, ID_SC_X100, ID_SC_RESET_PRICES,
       ID_SC_ACH_ALL, ID_SC_ACH_RESET, ID_SC_COL_ALL, ID_SC_COL_RESET };

static void RefreshStoreCheats(HWND dlg) {
    wchar_t s[96];
    if (gVillage.priceMultiplier == 1)
        swprintf(s, 96, L"Store prices: original");
    else
        swprintf(s, 96, L"Store prices: %dx", gVillage.priceMultiplier);
    SetDlgItemTextW(dlg, ID_SC_STATUS, s);
}

static INT_PTR CALLBACK StoreCheatsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: RefreshStoreCheats(dlg); return TRUE;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_SC_X2: gVillage.priceMultiplier = 2; break;
        case ID_SC_X5: gVillage.priceMultiplier = 5; break;
        case ID_SC_X100: gVillage.priceMultiplier = 100; break;
        case ID_SC_RESET_PRICES: gVillage.priceMultiplier = 1; break;
        case ID_SC_ACH_ALL:
            CompleteAllAchievements();
            Message(dlg, L"Every achievement is complete.");
            break;
        case ID_SC_ACH_RESET:
            if (MessageBoxW(dlg, L"Reset all goals and progress?", L"Reset Achievements", MB_YESNO | MB_ICONQUESTION) == IDYES)
                ResetAllAchievements(Achievements);
            break;
        case ID_SC_COL_ALL:
            CompleteCollections();
            Message(dlg, L"Every collection is complete.");
            break;
        case ID_SC_COL_RESET:
            if (MessageBoxW(dlg, L"Remove every collected item and reset collection progress?", L"Reset all collections", MB_YESNO | MB_ICONQUESTION) == IDYES)
                ResetCollections();
            break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); return TRUE;
        }
        RefreshStoreCheats(dlg);
        return TRUE;
    case WM_CLOSE: EndDialog(dlg, 0); return TRUE;
    }
    return FALSE;
}

static void ShowStoreCheats(HWND owner) {
    static Template t;
    t.Begin(L"Store, Achievement and Collection Cheats", 250, 170, 12);
    t.Item(STATIC, SS_LEFT, 10, 8, 230, 12, ID_SC_STATUS, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 24, 55, 16, ID_SC_X2, L"2x Prices");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 69, 24, 55, 16, ID_SC_X5, L"5x Prices");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 24, 55, 16, ID_SC_X100, L"100x Prices");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 187, 24, 53, 16, ID_SC_RESET_PRICES, L"Reset");
    t.Item(STATIC, SS_LEFT, 10, 50, 230, 12, -1, L"Achievements");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 64, 112, 16, ID_SC_ACH_ALL, L"Complete all Achievements");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 64, 112, 16, ID_SC_ACH_RESET, L"Reset Achievements");
    t.Item(STATIC, SS_LEFT, 10, 90, 230, 12, -1, L"Collections");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 104, 112, 16, ID_SC_COL_ALL, L"Complete all collections");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 104, 112, 16, ID_SC_COL_RESET, L"Reset all collections");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 146, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, StoreCheatsProc, 0);
}

// ---- House and yard
enum { ID_HY_TRASH = 520, ID_HY_CLEAN, ID_HY_WEEDS, ID_HY_GARDEN };

static INT_PTR CALLBACK HouseProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: return TRUE;
    case WM_COMMAND: {
        wchar_t s[96];
        switch (LOWORD(wp)) {
        case ID_HY_TRASH:
            if (gVillage.maid) { Message(dlg, L"The Maid is active, so the house stays clean."); break; }
            swprintf(s, 96, L"Spawned %d pieces of mess.", FillHouseWithTrash());
            Message(dlg, s);
            break;
        case ID_HY_CLEAN: CleanHouse(); Message(dlg, L"The house is clean."); break;
        case ID_HY_WEEDS:
            if (gVillage.gardener) { Message(dlg, L"The Gardener is active, so the yard stays weeded."); break; }
            swprintf(s, 96, L"Spawned %d weeds.", FillYardWithWeeds());
            Message(dlg, s);
            break;
        case ID_HY_GARDEN: CleanGarden(); Message(dlg, L"The garden is weeded."); break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); break;
        }
        return TRUE;
    }
    case WM_CLOSE: EndDialog(dlg, 0); return TRUE;
    }
    return FALSE;
}

static void ShowHouse(HWND owner) {
    static Template t;
    t.Begin(L"House and Yard", 250, 128, 6);
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 10, 230, 16, ID_HY_TRASH, L"Fill available house slots with trash (5 smudges, 5 socks, 5 wrappers)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 30, 230, 16, ID_HY_CLEAN, L"Clean House");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 54, 230, 16, ID_HY_WEEDS, L"Fill available yard slots with weeds (15)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 74, 230, 16, ID_HY_GARDEN, L"Clean Garden");
    t.Item(STATIC, SS_LEFT, 10, 96, 150, 24, -1, L"There are 30 mess slots in all, shared by the house and yard.");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 104, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, HouseProc, 0);
}

// ---- Special Upgrades (VF2's mobile purchases, plus the Maid and Gardener)
struct Purchase { int id; const wchar_t *name; int price; int VillageState::*owned; const wchar_t *what; };
enum { ID_SU_LIST = 540, ID_SU_BUY, ID_SU_DESC };
static const Purchase kPurchases[] = {
    { 0, L"Brokerage Account", 10000, &VillageState::brokerage, L"The bank's interest rate goes up 2 points, to at most 11%." },
    { 1, L"Food Club", 10000, &VillageState::foodClub, L"500 food right away, and 500 more every game day." },
    { 2, L"Health Plan", 10000, &VillageState::healthPlan, L"Medicines cost a quarter of the price." },
    { 3, L"Lucky Rock", 77777, &VillageState::luckyRock, L"Rare and uncommon collectibles turn up twice as often." },
    { 4, L"Maid", 1000, &VillageState::maid, L"Keeps the house clean: socks, wrappers, smudges and cobwebs. Buy again to let her go." },
    { 5, L"Gardener", 1000, &VillageState::gardener, L"Keeps the yard free of weeds. Buy again to let him go." },
};

static void FillPurchases(HWND dlg) {
    HWND list = GetDlgItem(dlg, ID_SU_LIST);
    int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    for (const Purchase &p : kPurchases) {
        wchar_t line[96];
        swprintf(line, 96, L"%s\t$%d%s", p.name, p.price, gVillage.*p.owned ? L"  (owned)" : L"");
        SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
    }
    SendMessageW(list, LB_SETCURSEL, sel < 0 ? 0 : sel, 0);
    sel = sel < 0 ? 0 : sel;
    SetDlgItemTextW(dlg, ID_SU_DESC, kPurchases[sel].what);
}

static INT_PTR CALLBACK PurchasesProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        int stop = 120;
        SendMessageW(GetDlgItem(dlg, ID_SU_LIST), LB_SETTABSTOPS, 1, (LPARAM)&stop);
        FillPurchases(dlg);
        return TRUE;
    }
    case WM_COMMAND: {
        HWND list = GetDlgItem(dlg, ID_SU_LIST);
        int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
        if (LOWORD(wp) == ID_SU_LIST && HIWORD(wp) == LBN_SELCHANGE && sel >= 0) {
            SetDlgItemTextW(dlg, ID_SU_DESC, kPurchases[sel].what);
        } else if (LOWORD(wp) == ID_SU_BUY && sel >= 0) {
            const Purchase &p = kPurchases[sel];
            int &owned = gVillage.*p.owned;
            if (owned && (p.owned == &VillageState::maid || p.owned == &VillageState::gardener)) {
                owned = 0;                         // VF2: buying again fires the worker
            } else if (owned) {
                Message(dlg, L"You already have this.");
            } else if (CurrentMoney() < p.price) {
                Message(dlg, L"You don't have enough money for that.");
            } else {
                MoneyAdjust(Money, (float)-p.price, false);
                owned = 1;
                if (p.owned == &VillageState::foodClub) {
                    FoodAdjust(Food, 500);
                    gVillage.foodClubLast = GameSeconds(GameTime);
                }
            }
            ApplyVillageEffects();
            FillPurchases(dlg);
        } else if (LOWORD(wp) == IDOK || LOWORD(wp) == IDCANCEL) {
            EndDialog(dlg, 0);
        }
        return TRUE;
    }
    case WM_CLOSE: EndDialog(dlg, 0); return TRUE;
    }
    return FALSE;
}

static void ShowPurchases(HWND owner) {
    static Template t;
    t.Begin(L"Special Upgrades", 250, 180, 4);
    t.Item(LISTBOX, LBS_NOTIFY | LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 10, 10, 230, 90, ID_SU_LIST, L"");
    t.Item(STATIC, SS_LEFT, 10, 106, 230, 36, ID_SU_DESC, L"");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 10, 156, 75, 16, ID_SU_BUY, L"Buy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 165, 156, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, PurchasesProc, 0);
}

// ---- Time controls
enum { ID_TC_STATUS = 560, ID_TC_PAUSE, ID_TC_RESUME, ID_TC_NORMAL, ID_TC_X2, ID_TC_X5, ID_TC_X10,
       ID_TC_WARP1, ID_TC_WARP5 };

static void RefreshTime(HWND dlg) {
    wchar_t s[128];
    const wchar_t *speed = gWantedSpeed == 5 ? L"2x" : gWantedSpeed == 2 ? L"5x" : gWantedSpeed == 1 ? L"10x" : L"normal";
    swprintf(s, 128, L"%s. Speed: %s.%s", GamePaused() ? L"Paused" : L"Running", speed,
             gWarpTicks ? L" A time warp is under way." : L"");
    SetDlgItemTextW(dlg, ID_TC_STATUS, s);
}

static INT_PTR CALLBACK TimeProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: RefreshTime(dlg); return TRUE;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_TC_PAUSE: PauseGame(); break;
        case ID_TC_RESUME: ResumeGame(); break;
        case ID_TC_NORMAL: gWantedSpeed = 10; if (!GamePaused()) { SetSpeed(GameTime, 10); *GameSpeedSlot() = 10; } break;
        case ID_TC_X2: gWantedSpeed = 5; ApplyGameSpeed(); break;
        case ID_TC_X5: gWantedSpeed = 2; ApplyGameSpeed(); break;
        case ID_TC_X10: gWantedSpeed = 1; ApplyGameSpeed(); break;
        case ID_TC_WARP1: case ID_TC_WARP5:
            if (MessageBoxW(dlg, L"Everyone at home ages at once, with every normal rule: birthdays, leaving home, "
                                 L"and old age. Continue?", L"Time Warp", MB_YESNO | MB_ICONQUESTION) == IDYES)
                StartTimeWarp(LOWORD(wp) == ID_TC_WARP1 ? 20 : 100);
            break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); return TRUE;
        }
        RefreshTime(dlg);
        return TRUE;
    case WM_CLOSE: EndDialog(dlg, 0); return TRUE;
    }
    return FALSE;
}

static void ShowTime(HWND owner) {
    static Template t;
    t.Begin(L"Time Controls", 250, 150, 10);
    t.Item(STATIC, SS_LEFT, 10, 8, 230, 12, ID_TC_STATUS, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 24, 112, 16, ID_TC_PAUSE, L"Pause");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 24, 112, 16, ID_TC_RESUME, L"Resume");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 48, 53, 16, ID_TC_NORMAL, L"Normal");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 69, 48, 53, 16, ID_TC_X2, L"2x");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 48, 53, 16, ID_TC_X5, L"5x");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 187, 48, 53, 16, ID_TC_X10, L"10x");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 76, 112, 16, ID_TC_WARP1, L"Time Warp: +1 year");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 76, 112, 16, ID_TC_WARP5, L"Time Warp: +5 years");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 126, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, TimeProc, 0);
}
