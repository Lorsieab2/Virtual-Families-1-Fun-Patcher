// patcher_achievements.inc -- the Virtual Families 2 patcher's custom
// achievements that make sense in Virtual Families 1, with the same names and
// wording, one bit each in gVillage.achievements (saved per village in the
// sidecar as "PatcherAchievements"). They are separate from the game's Trophies
// screen, whose table is fixed in the executable, so the Upgrades menu shows
// them on their own page. A new village starts with none (theGameState::Init
// resets gVillage).
//
// Left out because VF1 cannot meet them: "No More Worries" and "Solving World
// Hunger" (VF1 has no maximum coins or food: CMoney::Adjust and
// CFoodStore::Adjust never clamp upward), the pet goals, and the behavior,
// holiday, birthday and furniture goals (VF1 has none of those items or
// behaviors).
//
// The state is read live every 15 seconds on the main scene (CheckAchievements,
// from FeaturesTick) and when the page opens.
struct PatcherAchievement { const wchar_t *name; const wchar_t *how; };
enum { ACH_LUCKY_70, ACH_GREAT_80, ACH_MIGHTY_90, ACH_CENTENARIAN, ACH_OLDEST_IN_HISTORY, ACH_RAINBOW, ACH_SPIKY,
       ACH_EXTRAORDINAIRE, ACH_COUNT };
static const PatcherAchievement kAchievements[ACH_COUNT] = {
    { L"Lucky 70's", L"Have a person reach age 70." },
    { L"Great 80's", L"Have a person reach age 80." },
    { L"Mighty 90's", L"Have a person reach age 90." },
    { L"Centenarian", L"Have a person reach age 100 or more." },
    { L"Oldest Person in History", L"Have a person surpass age 122." },
    { L"Return of the Rainbow", L"Have a female villager with head value 49 in the family tree." },
    { L"Spiky!", L"Have a male villager with head value 48 in the family tree." },
    { L"Achiever Extraordinaire", L"Complete every enabled achievement." },
};

// VF1's head sheets have rows 0-49. Return of the Rainbow is the female sheet's last
// row (49, the rainbow hair); Spiky! is the male sheet's second-to-last row (48, the
// black mohawk), as the owner specified.
static const int kLastHead = 49;

static int AchievementsUnlocked() {
    int n = 0;
    for (int i = 0; i < ACH_COUNT; ++i)
        if (gVillage.achievements & (1u << i)) ++n;
    return n;
}

static void UnlockAchievement(int bit) {
    if (bit < 0 || bit >= ACH_COUNT || (gVillage.achievements & (1u << bit)))
        return;
    gVillage.achievements |= 1u << bit;
}

// CFamilyTree records (0x5AB908 + 4 + i * 0x6C8): +4 parent-1 and +0xDC
// parent-2 SPeepRecords, +0x1B4 child count, +0x1B8 children. SPeepRecord:
// +0x1A used, +0x1C gender (0 male, 1 female), +0x20 head.
static bool FamilyTreeHas(int gender, int head) {
    for (int r = 0; r < 30; ++r) {
        unsigned char *rec = (unsigned char *)(0x5AB908 + 4 + r * 0x6C8);
        if (!rec[0]) continue;
        unsigned char *peeps[8];
        int n = 0;
        peeps[n++] = rec + 4;
        peeps[n++] = rec + 0xDC;
        int children = *(int *)(rec + 0x1B4);
        for (int c = 0; c < children && c < 6; ++c) peeps[n++] = rec + 0x1B8 + c * 0xD8;
        for (int i = 0; i < n; ++i)
            if (peeps[i][0x1A] && *(int *)(peeps[i] + 0x1C) == gender && *(int *)(peeps[i] + 0x20) == head)
                return true;
    }
    return false;
}

static void CheckAchievements() {
    int oldest = OldestEverAge();
    if (oldest >= 70) UnlockAchievement(ACH_LUCKY_70);
    if (oldest >= 80) UnlockAchievement(ACH_GREAT_80);
    if (oldest >= 90) UnlockAchievement(ACH_MIGHTY_90);
    if (oldest >= 100) UnlockAchievement(ACH_CENTENARIAN);
    if (oldest > 122) UnlockAchievement(ACH_OLDEST_IN_HISTORY);
    if (FamilyTreeHas(1, kLastHead)) UnlockAchievement(ACH_RAINBOW);
    if (FamilyTreeHas(0, kLastHead - 1)) UnlockAchievement(ACH_SPIKY);
    if (AchievementsUnlocked() == ACH_COUNT - 1) UnlockAchievement(ACH_EXTRAORDINAIRE);
}

enum { ID_PA_LIST = 760 };

static INT_PTR CALLBACK AchievementsProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        CheckAchievements();
        HWND list = GetDlgItem(dlg, ID_PA_LIST);
        int stop = 120;
        SendMessageW(list, LB_SETTABSTOPS, 1, (LPARAM)&stop);
        for (int i = 0; i < ACH_COUNT; ++i) {
            wchar_t line[200];
            swprintf(line, 200, L"%s %s\t%s", (gVillage.achievements & (1u << i)) ? L"[x]" : L"[  ]",
                     kAchievements[i].name, kAchievements[i].how);
            SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
        }
        wchar_t s[64];
        swprintf(s, 64, L"%d of %d unlocked", AchievementsUnlocked(), (int)ACH_COUNT);
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
    t.Begin(L"Patcher Achievements", 420, 150, 3);
    t.Item(LISTBOX, LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER, 10, 10, 400, 100, ID_PA_LIST, L"");
    t.Item(STATIC, SS_LEFT, 10, 124, 150, 12, ID_PA_LIST + 1, L"");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 335, 128, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, AchievementsProc, 0);
}
