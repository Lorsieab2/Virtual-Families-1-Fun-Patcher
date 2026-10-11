// patcher_achievements.inc -- the patcher's own milestones, one bit each in
// gVillage.achievements, saved per village in the sidecar ("PatcherAchievements").
// They are separate from the game's Trophies screen (whose table is fixed in
// the executable): the Upgrades menu shows them in their own page. A new
// village starts with none (theGameState::Init resets gVillage).
//
// Milestones read live game state every 15 seconds on the main scene
// (CheckAchievements, from FeaturesTick); the family ones are unlocked by the
// feature itself.
struct PatcherAchievement { const wchar_t *name; const wchar_t *how; };
static const PatcherAchievement kAchievements[] = {
    { L"Golden Years", L"A villager reaches 90 years old." },
    { L"Centenarian", L"A villager reaches 100 years old." },
    { L"Beyond the Curve", L"A villager reaches 122 years old." },
    { L"Dynasty", L"Reach the fifth generation." },
    { L"Legacy", L"Reach the tenth generation." },
    { L"Full House", L"Ten villagers in the house at once." },
    { L"Rainbow Wedding", L"Marry a same-sex couple." },
    { L"Fresh Start", L"Evict your family and adopt a new one." },
    { L"Amicable Split", L"Divorce a spouse." },
    { L"Second Chance", L"Adopt a new person after losing the family." },
};
static const int kAchievementCount = (int)(sizeof kAchievements / sizeof kAchievements[0]);

static int AchievementsUnlocked() {
    int n = 0;
    for (int i = 0; i < kAchievementCount; ++i)
        if (gVillage.achievements & (1u << i)) ++n;
    return n;
}

static void UnlockAchievement(int bit) {
    if (bit < 0 || bit >= kAchievementCount || (gVillage.achievements & (1u << bit)))
        return;
    gVillage.achievements |= 1u << bit;
}

static void CheckAchievements() {
    int oldest = OldestEverAge();
    if (oldest >= 90) UnlockAchievement(0);
    if (oldest >= 100) UnlockAchievement(1);
    if (oldest >= 122) UnlockAchievement(2);
    int generation = GenerationNumber();
    if (generation >= 5) UnlockAchievement(3);
    if (generation >= 10) UnlockAchievement(4);
    int inHouse = 0;
    for (int i = 0; i < VillagerSlots; ++i)
        if (VillagerPresent(i) && !Villager(i)[0x13578]) ++inHouse;
    if (inHouse >= 10) UnlockAchievement(5);
}

enum { ID_PA_LIST = 760 };

static INT_PTR CALLBACK AchievementsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        CheckAchievements();
        HWND list = GetDlgItem(dlg, ID_PA_LIST);
        int stop = 100;
        SendMessageW(list, LB_SETTABSTOPS, 1, (LPARAM)&stop);
        for (int i = 0; i < kAchievementCount; ++i) {
            wchar_t line[160];
            swprintf(line, 160, L"%s %s\t%s", (gVillage.achievements & (1u << i)) ? L"[x]" : L"[  ]",
                     kAchievements[i].name, kAchievements[i].how);
            SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
        }
        wchar_t s[64];
        swprintf(s, 64, L"%d of %d unlocked", AchievementsUnlocked(), kAchievementCount);
        SetDlgItemTextW(dlg, ID_PA_LIST + 1, s);
        return TRUE;
    }
    case WM_COMMAND:
        if (LOWORD(wp) == IDOK || LOWORD(wp) == IDCANCEL) EndDialog(dlg, 0);
        return TRUE;
    case WM_CLOSE:
        EndDialog(dlg, 0);
        return TRUE;
    }
    return FALSE;
}

static void ShowAchievements(HWND owner) {
    static Template t;
    t.Begin(L"Patcher Achievements", 330, 170, 3);
    t.Item(LISTBOX, LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER, 10, 10, 310, 120, ID_PA_LIST, L"");
    t.Item(STATIC, SS_LEFT, 10, 140, 150, 12, ID_PA_LIST + 1, L"");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 245, 148, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, AchievementsProc, 0);
}
