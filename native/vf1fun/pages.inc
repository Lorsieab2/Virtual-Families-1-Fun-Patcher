// pages.inc -- the Upgrades menu's newer pages; included after features.inc.

static int GenerationNumber() { return *(int *)0x5AB908; }     // CFamilyTree+0, starts at 1
// The Upgrades menu's "Oldest Villager" (and the longevity achievements) use the game's own record
// (CGameStats+0x20, years, saved with the village) unless it is obviously cheated: an age no family
// reaches (over 150 years, the longest the mortality curves leave anyone alive) is ignored, and the oldest
// villager in the house now stands in for it. The Family Tree stores no ages, so it cannot supply one.
// "Generation" is the Family Tree's own count (CFamilyTree+0, starting at 1).
static const int kBelievableOldestYears = 150;
static int OldestEverAge() {
    int recorded = *(int *)0x50C580;
    if (recorded <= kBelievableOldestYears) return recorded;
    int oldest = 0;
    for (int i = 0; i < 30; ++i) {
        unsigned char *v = (unsigned char *)0x5B8898 + 0x14640 + i * 0x145FC;
        if (!v[0x13574]) continue;
        int years = *(int *)(v + 0x2A34) / 20;
        if (years <= kBelievableOldestYears && years > oldest) oldest = years;
    }
    return oldest;
}

// ---- Store, achievement and collection cheats (VF2 wording)
enum { ID_SC_STATUS = 500, ID_SC_X2, ID_SC_X5, ID_SC_X100, ID_SC_RESET_PRICES,
       ID_SC_ACH_ALL, ID_SC_ACH_RESET, ID_SC_COL_ALL, ID_SC_COL_RESET, ID_SC_ANTISPAM };
static bool AntiSpamOwned();
static void SetAntiSpam(bool on);

static void RefreshStoreCheats(HWND dlg) {
    wchar_t s[96];
    if (gVillage.priceMultiplier == 1)
        swprintf(s, 96, L"Store prices: original");
    else
        swprintf(s, 96, L"Store prices: %dx", gVillage.priceMultiplier);
    wcscat_s(s, 96, AntiSpamOwned() ? L"     Anti-spam: installed" : L"     Anti-spam: not installed");
    SetDlgItemTextW(dlg, ID_SC_STATUS, s);
}

static INT_PTR CALLBACK StoreCheatsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG:
        HideWithoutFreeCheats(dlg, ID_SC_ANTISPAM);
        RefreshStoreCheats(dlg);
        return TRUE;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        // VF2: buying the price mode you already have takes it away again.
        case ID_SC_X2: gVillage.priceMultiplier = gVillage.priceMultiplier == 2 ? 1 : 2; break;
        case ID_SC_X5: gVillage.priceMultiplier = gVillage.priceMultiplier == 5 ? 1 : 5; break;
        case ID_SC_X100: gVillage.priceMultiplier = gVillage.priceMultiplier == 100 ? 1 : 100; break;
        case ID_SC_RESET_PRICES: gVillage.priceMultiplier = 1; break;
        // VF2's "Anti-Spam Software Ownership" cheat (item 0x158): free; buying it again switches it back.
        // Free: it needs Free and Guaranteed Cheats.
        case ID_SC_ANTISPAM: if (!FreeCheatsRefused(dlg)) SetAntiSpam(!AntiSpamOwned()); break;
        case ID_SC_ACH_ALL:
            if (Confirm(dlg, L"Complete every achievement? Reset Achievements is the only way back.")) {
                CompleteAllAchievements();
                Message(dlg, L"Every achievement is complete.");
            }
            break;
        case ID_SC_ACH_RESET:
            if (MessageBoxW(dlg, L"Reset all goals and progress?", L"Reset Achievements", MB_YESNO | MB_ICONQUESTION) == IDYES)
                ResetAllAchievements(Achievements);
            break;
        case ID_SC_COL_ALL:
            if (Confirm(dlg, L"Complete every collection?")) {
                CompleteCollections();
                Message(dlg, L"Every collection is complete.");
            }
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
    t.Begin(L"Store, Achievement and Collection Cheats", 250, 194, 13);
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
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 130, 230, 16, ID_SC_ANTISPAM, L"Anti-Spam Software Ownership (install / uninstall)");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 170, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, StoreCheatsProc, 0);
}

// ---- House and yard
enum { ID_HY_TRASH = 520, ID_HY_CLEAN, ID_HY_WEEDS, ID_HY_GARDEN, ID_HY_BREAK, ID_HY_FIX };

// The eight props the game's random malfunction picks from (theMainScene
// UpdateScene 0x444ECD): 0x16 power failure, 0x19/0x1A/0x1B/0x1C/0x1E leaks
// and clogs, 0x1F/0x20 fires. CEnvironment (0x8752F0): SetProp 0x4938C0,
// ClearProp 0x493CF0, active byte at +4+8*prop. The game's own events and
// repairs call these two functions the same way.
typedef void (__thiscall *PropFn)(void *environment, int prop);
static const int kMalfunctionProps[] = { 0x16, 0x19, 0x1A, 0x1B, 0x1C, 0x1E, 0x1F, 0x20 };
static bool PropActive(int prop) { return *(unsigned char *)(0x8752F4 + 8 * prop) != 0; }
static int SetAllMalfunctions(bool on) {
    int changed = 0;
    for (int prop : kMalfunctionProps) {
        if (PropActive(prop) == on) continue;
        ((PropFn)(on ? 0x4938C0 : 0x493CF0))((void *)0x8752F0, prop);
        ++changed;
    }
    return changed;
}

static INT_PTR CALLBACK HouseProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: return TRUE;
    case WM_COMMAND: {
        wchar_t s[96];
        switch (LOWORD(wp)) {
        case ID_HY_TRASH:
            swprintf(s, 96, L"Spawned %d pieces of mess.", FillHouseWithTrash());
            Message(dlg, s);
            break;
        case ID_HY_CLEAN: CleanHouse(); Message(dlg, L"The house is clean."); break;
        case ID_HY_WEEDS:
            swprintf(s, 96, L"Spawned %d weeds.", FillYardWithWeeds());
            Message(dlg, s);
            break;
        case ID_HY_GARDEN: CleanGarden(); Message(dlg, L"The garden is weeded."); break;
        case ID_HY_BREAK:
            SetAllMalfunctions(true);  // some may already have been active
            swprintf(s, 96, L"All %d house malfunctions are now active.", (int)(sizeof kMalfunctionProps / sizeof kMalfunctionProps[0]));
            Message(dlg, s);
            break;
        case ID_HY_FIX:
            swprintf(s, 96, L"Fixed %d malfunctions.", SetAllMalfunctions(false));
            Message(dlg, s);
            break;
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
    t.Begin(L"House and Yard", 250, 172, 8);
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 10, 230, 16, ID_HY_TRASH, L"Fill available house slots with trash (5 smudges, 5 socks, 5 wrappers)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 30, 230, 16, ID_HY_CLEAN, L"Clean House");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 54, 230, 16, ID_HY_WEEDS, L"Fill available yard slots with weeds (15)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 74, 230, 16, ID_HY_GARDEN, L"Clean Garden");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 98, 230, 16, ID_HY_BREAK, L"Trigger all house malfunctions (leaks, clogs, fires, power failure)");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 118, 230, 16, ID_HY_FIX, L"Fix all house malfunctions");
    t.Item(STATIC, SS_LEFT, 10, 140, 150, 24, -1, L"There are 30 mess slots in all, shared by the house and yard.");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 148, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, HouseProc, 0);
}

// ---- Special Upgrades (VF2's mobile purchases, plus the Maid and Gardener)
// Anti-spam Software (item 47, $125): the game's own record of owning it is the byte at
// theGameState+0x1CC (set when the software is dropped on a computer, 0x442DA5; the spam
// events test it, 0x417C35), and the game saves it.
static bool AntiSpamOwned() { return ((unsigned char *)GameStateGet())[0x1CC] != 0; }
static void SetAntiSpam(bool on) { ((unsigned char *)GameStateGet())[0x1CC] = on ? 1 : 0; }

struct Purchase {
    int id; const wchar_t *name; int price;
    int VillageState::*owned;
    const wchar_t *what;
};
static int BankRate() { return gVillage.bankRate ? gVillage.bankRate : 10; }
// VF2ApplyVisibleSpecialUpgrade 0x117: the Brokerage Account is "owned" while the rate is above 10%.
static bool PurchaseOwned(const Purchase &p) {
    if (p.owned == &VillageState::brokerage) return BankRate() > 10;
    return gVillage.*p.owned != 0;
}
// VF2's Brokerage Account: buying adds 2 points (at most 11%); buying it while owned sets the rate to 1%.
static void BuyBrokerage() {
    int rate = BankRate();
    gVillage.bankRate = rate > 10 ? 1 : (rate + 2 > 11 ? 11 : rate + 2);
    gVillage.brokerage = gVillage.bankRate > 10;
}
static int PurchasePrice(const Purchase &p) { return p.price; }
enum { ID_SU_LIST = 540, ID_SU_BUY, ID_SU_DESC };
static const Purchase kPurchases[] = {
    { 0, L"Brokerage Account", 10000, &VillageState::brokerage, L"Upgrade your broker: a permanent 2% boost to your family's banking interest rate, up to 11%. Buy again to remove it: the rate then drops to 1%, as in the Virtual Families 2 patcher." },
    { 1, L"Food Club", 10000, &VillageState::foodClub, L"It's a CSA (Community Sources Agriculture) subscription! Bags of organic, local groceries containing all 4 food groups, delivered each day (helps prevent accidental starvation). Plus a permanent 50% discount on all food! Buy again to remove it." },
    { 2, L"Health Plan", 10000, &VillageState::healthPlan, L"A permanent 75% discount on all health care and medicines. Buy again to remove it." },
    { 3, L"Lucky Rock", 77777, &VillageState::luckyRock, L"This lucky rock increases the rate and rarity of random collectibles that appear in the yard. Buy again to remove it." },
    { 4, L"Maid", 1000, &VillageState::maid, L"No more stray wrappers and socks, ever! A maid comes every game hour during the day. Buy again to let her go." },
    { 5, L"Gardener", 1000, &VillageState::gardener, L"Had enough of pulling weeds? A gardener comes every game hour during the day. Buy again to let him go." },
};

static void FillPurchases(HWND dlg) {
    HWND list = GetDlgItem(dlg, ID_SU_LIST);
    int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    for (const Purchase &p : kPurchases) {
        wchar_t line[96];
        swprintf(line, 96, L"%s\t$%d%s", p.name, PurchasePrice(p), PurchaseOwned(p) ? L"  (owned)" : L"");
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
            wchar_t text[300];
            if (PurchaseOwned(p)) {
                // As in the Virtual Families 2 patcher: buying an upgrade again removes it (no refund).
                swprintf(text, 300, L"Remove %s? It is not refunded, and you can buy it again later.", p.name);
                if (Confirm(dlg, text)) {
                    if (p.owned == &VillageState::brokerage) BuyBrokerage();
                    else gVillage.*p.owned = 0;
                    swprintf(text, 300, L"%s removed.", p.name);
                    Message(dlg, text);
                }
            } else if (CurrentMoney() < PurchasePrice(p)) {
                Message(dlg, L"You don't have enough money for that.");
            } else {
                swprintf(text, 300, L"Buy %s for $%d?", p.name, PurchasePrice(p));
                if (Confirm(dlg, text)) {
                    MoneyAdjust(Money, (float)-PurchasePrice(p), false);
                    swprintf(text, 300, L"Purchased: %s.", p.name);
                    // VF2's purchase popups.
                    if (p.owned == &VillageState::brokerage) BuyBrokerage();
                    else if (p.owned == &VillageState::foodClub) {
                        FoodClubJoin();
                        swprintf(text, 300, L"You are signed up for the Food Club!\n\nYou have received a food delivery "
                                            L"containing the 4 food groups!\nYou will now get a new food delivery every day.");
                    } else if (p.owned == &VillageState::maid) {
                        gVillage.maid = 1; HireHelper(&gVillage.maidNext);
                        swprintf(text, 300, L"You have a maid! Now the house will always be clean.");
                    } else if (p.owned == &VillageState::gardener) {
                        gVillage.gardener = 1; HireHelper(&gVillage.gardenerNext);
                        swprintf(text, 300, L"You have a gardener! No more pesky weeds.");
                    } else gVillage.*p.owned = 1;
                    Message(dlg, text);
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
    t.Item(STATIC, SS_LEFT, 10, 104, 230, 48, ID_SU_DESC, L"");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 10, 156, 75, 16, ID_SU_BUY, L"Buy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 165, 156, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, PurchasesProc, 0);
}

// ---- Time controls
enum { ID_TC_STATUS = 560, ID_TC_PAUSE, ID_TC_RESUME, ID_TC_NORMAL, ID_TC_X2, ID_TC_X5, ID_TC_X10,
       ID_TC_WARP, ID_TC_SLOW };
// Slow / Normal / Fast are VF1's own engine speeds, the same three the Virtual Villagers games offer: the
// time-flow upkeep (0x489E08) knows exactly 20 (slow, half speed), 10 (normal) and 5 (fast, 2x), each with
// its own catch-up cap (0x5CF8 / 0x7918 / 0x9538 seconds). 5x and 10x stay as extra choices.
static const int kSpeedSlow = 20;

static void RefreshTime(HWND dlg) {
    wchar_t s[128];
    const wchar_t *speed = gWantedSpeed == kSpeedSlow ? L"slow" : gWantedSpeed == 5 ? L"fast (2x)" : gWantedSpeed == 2 ? L"5x" : gWantedSpeed == 1 ? L"10x" : L"normal";
    swprintf(s, 128, L"%s. Speed: %s.", GamePaused() ? L"Paused" : L"Running", speed);
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
        case ID_TC_SLOW: gWantedSpeed = kSpeedSlow; ApplyGameSpeed(); break;
        case ID_TC_X2: gWantedSpeed = 5; ApplyGameSpeed(); break;
        case ID_TC_X5: gWantedSpeed = 2; ApplyGameSpeed(); break;
        case ID_TC_X10: gWantedSpeed = 1; ApplyGameSpeed(); break;
        // Time Warp is VF2's paid Special Upgrade now, on the Services page (SpecialUpgrades), not a cheat.
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
    t.Begin(L"Time Controls", 250, 124, 9);
    t.Item(STATIC, SS_LEFT, 10, 8, 230, 12, ID_TC_STATUS, L"");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 24, 112, 16, ID_TC_PAUSE, L"Pause");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 24, 112, 16, ID_TC_RESUME, L"Resume");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 48, 73, 16, ID_TC_SLOW, L"Slow");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 88, 48, 74, 16, ID_TC_NORMAL, L"Normal");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 167, 48, 73, 16, ID_TC_X2, L"Fast");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 10, 70, 112, 16, ID_TC_X5, L"5x");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 128, 70, 112, 16, ID_TC_X10, L"10x");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 165, 100, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, TimeProc, 0);
}
