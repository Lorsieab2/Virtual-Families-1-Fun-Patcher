// services.inc -- the Upgrades menu's Services page: the Virtual Families 2 store's services and its Time Warp
// and Adoption Services Special Upgrades, sold for coins at VF2's prices (setting SpecialUpgrades, on by
// default; the owner, 2026-11-01: "Include in VF1 all things that VF2 has already"). Included after
// villager_upgrades.inc and family.inc.
//
// The prices and effects are VF2's (the VF2 Fun Patcher's Game Mechanics page, vf2_game_mechanics.py
// SPECIAL_ITEMS / SERVICE_ITEMS, read from VF2's own store code):
//   Time Warp                   $2,000  the family lives 61 age units at once; the money it brings is capped at $750
//   Adoption Services           $4,000  a 3-year-old (60 age units) of either sex, equally likely, joins the house
//                                       and the family tree as a child
//   Boarding School             $1,500  children: leaves home as a child going to college does
//   Systematic Desensitization  $2,500  every dislike is removed
//   Psychotherapy               $1,750  happiness below 25 becomes 30-49; 25-49 becomes 55-74; from 50 it rises
//                                       by 5-24 (at most 100)
//   Higher Learning Classes     $1,000  one new like, at random from the likes not already liked, if one of the 3
//                                       like places is free; that like is taken off the dislikes
//   Advanced Career Training    $1,100 x (career level + 1), adults: a promotion with its new salary; nothing is
//                                       sold at Master (level 7)
//   Career Change               $1,200  adults: a new career at random, at Beginner
// VF1's own data is used where the rule reads game data: VF1's likes and dislikes lists (strings 0x45B / 0x45C,
// matched by name), its 108 careers (VF2 has 132) and its game calls (AdvanceCareer 0x48F590, ResetCareer
// 0x48F020, SetLeftHome 0x4857F0, the Little Visitor's adoption). With Free and Guaranteed Cheats on, every one
// is free. Nothing is charged unless the service is done: a family member it cannot help is refused first, and
// a family that cannot afford it is refused with nothing changed.

enum { SV_TIME_WARP, SV_ADOPTION, SV_BOARDING, SV_DESENS, SV_PSYCHO, SV_LEARN, SV_TRAINING, SV_CAREER, SV_COUNT };
struct Service { const wchar_t *name; int price; bool member; const wchar_t *what; };
static const Service kServices[SV_COUNT] = {
    { L"Time Warp", 2000, false, L"The whole family lives 3 years (61 age units) at once, with their meals, health, "
      L"salary and birthdays. The money it brings is capped at $750." },
    { L"Adoption Services", 4000, false, L"Spawn outside child in house (3 years old, male or female at random): "
      L"the child joins the house at once and the family tree as an adopted child, with the game's own random look. "
      L"No event text or popup." },
    { L"Boarding School", 1500, true, L"Children only: the child leaves home, as a child going to college does." },
    { L"Systematic Desensitization", 2500, true, L"Every dislike of this family member is removed." },
    { L"Psychotherapy", 1750, true, L"Happiness below 25 becomes 30 to 49; from 25 to 49 it becomes 55 to 74; from "
      L"50 it rises by 5 to 24 (at most 100)." },
    { L"Higher Learning Classes", 1000, true, L"One new like, at random from the likes this family member does not "
      L"have, if one of the 3 like places is free. That like is taken off the dislikes." },
    { L"Advanced Career Training", 1100, true, L"Adults with a career: a promotion to the next career level, with its "
      L"new salary. $1,100 times (the career level + 1): $1,100 for a Beginner up to $7,700 for an Exceptional; "
      L"nothing is sold to a Master." },
    { L"Career Change", 1200, true, L"Adults with a career: a new career at random, at Beginner." },
};
static const int kTopCareerLevel = 7;  // Master (strings 0x1C1..0x1C8: Beginner .. Master)
static int CareerLevel(int i) { return *(int *)(Villager(i) + 0x2B70); }

// The price for this family member (who; -1 for a family-wide item), or -1 when it is not sold to them.
static int ServicePrice(int item, int who) {
    if (item < 0 || item >= SV_COUNT) return -1;
    int price = kServices[item].price;
    if (item == SV_TRAINING) {
        if (who < 0 || !HasCareer(who) || CareerLevel(who) >= kTopCareerLevel) return -1;
        price = 1100 * (CareerLevel(who) + 1);
    }
    return gFreeCheats ? 0 : price;
}

// Why this family member cannot have it (nothing is charged), or 0.
static const wchar_t *ServiceRefusal(int item, int who) {
    if (!CurrentFamily()) return L"There is no family yet.";
    if (!kServices[item].member) return 0;
    if (who < 0 || who >= VillagerSlots || !VillagerPresent(who) || Villager(who)[0x13578])
        return L"Pick a family member at home first.";
    switch (item) {
    case SV_BOARDING: return HasCareer(who) ? L"Boarding School is for children only." : 0;
    case SV_DESENS: {
        int *d = Dislikes(who);
        return d[0] == -1 && d[1] == -1 && d[2] == -1 ? L"This family member has no dislikes." : 0;
    }
    case SV_LEARN: {
        int *l = Likes(who);
        return l[0] != -1 && l[1] != -1 && l[2] != -1 ? L"Every like place is already full." : 0;
    }
    case SV_TRAINING:
        if (!HasCareer(who)) return L"Advanced Career Training is for adults with a career.";
        return CareerLevel(who) >= kTopCareerLevel ? L"This family member is already a Master: nothing to train." : 0;
    case SV_CAREER: return HasCareer(who) ? 0 : L"Career Change is for adults with a career.";
    }
    return 0;
}

static const wchar_t *RemoveEveryDislike(int i) {
    int *d = Dislikes(i);
    for (int s = 0; s < 3; ++s) d[s] = -1;
    return 0;
}

// VF2's Psychotherapy bands, with VF1's happiness (0..100).
static const wchar_t *PsychotherapyBands(int i) {
    int *h = Stat(i, STAT_HAPPINESS);
    if (*h < 25) *h = 30 + GetRandom(20);
    else if (*h < 50) *h = 55 + GetRandom(20);
    else { *h += 5 + GetRandom(20); if (*h > 100) *h = 100; }
    return 0;
}

// VF2's Higher Learning Classes: a like picked at random among those not already liked (a disliked one may be
// picked: it then leaves the dislikes), into a free like place.
static const wchar_t *HigherLearning(int i) {
    const char *likes = LikeNames();
    int total = NameCount(likes);
    int *l = Likes(i);
    int candidates = 0;
    for (int k = 0; k < total; ++k)
        if (l[0] != k && l[1] != k && l[2] != k) ++candidates;
    if (candidates <= 0) return L"Nothing new to learn.";
    int pick = GetRandom(candidates);
    for (int k = 0; k < total; ++k) {
        if (l[0] == k || l[1] == k || l[2] == k) continue;
        if (pick-- == 0) {
            char name[48];
            if (!NameAt(likes, k, name, sizeof name)) return L"The game has no likes list.";
            return GiveLike(i, name);
        }
    }
    return L"Nothing new to learn.";
}

static const wchar_t *DoService(int item, int who) {
    switch (item) {
    case SV_TIME_WARP: TimeWarp(); return 0;
    case SV_ADOPTION: return AdoptOutsideChild(GetRandom(2), 3, 0);
    case SV_BOARDING: return BoardingSchool(who);
    case SV_DESENS: return RemoveEveryDislike(who);
    case SV_PSYCHO: return PsychotherapyBands(who);
    case SV_LEARN: return HigherLearning(who);
    case SV_TRAINING: PromoteVillager(who); return 0;
    case SV_CAREER: ChangeCareer(who); return 0;
    }
    return L"There is no such service.";
}

// Buys one service: refused (0 charged, nothing changed) when it is not for this family member or the family
// cannot afford it; otherwise the service is done and its price is paid. Returns 0 when bought, or the reason.
static const wchar_t *BuyService(int item, int who) {
    if (item < 0 || item >= SV_COUNT) return L"There is no such service.";
    if (!kServices[item].member) who = -1;
    const wchar_t *why = ServiceRefusal(item, who);
    if (why) return why;
    int price = ServicePrice(item, who);
    if (price < 0) return L"That is not sold to this family member.";
    if (CurrentMoney() < price) return L"You don't have enough money for that.";
    why = DoService(item, who);
    if (why) return why;
    if (price) MoneyAdjust(Money, (float)-price, false);
    return 0;
}

// ---- the page
enum { ID_SV_MONEY = 580, ID_SV_WHO, ID_SV_LIST, ID_SV_DESC, ID_SV_BUY };

static int SelectedMember(HWND dlg) {
    HWND who = GetDlgItem(dlg, ID_SV_WHO);
    int sel = (int)SendMessageW(who, LB_GETCURSEL, 0, 0);
    return sel < 0 ? -1 : (int)SendMessageW(who, LB_GETITEMDATA, sel, 0);
}

static void FillServices(HWND dlg) {
    wchar_t s[96];
    swprintf(s, 96, L"Money: $%.0f%s", CurrentMoney(), gFreeCheats ? L"     (Free and Guaranteed Cheats: all free)" : L"");
    SetDlgItemTextW(dlg, ID_SV_MONEY, s);
    int who = SelectedMember(dlg);
    HWND list = GetDlgItem(dlg, ID_SV_LIST);
    int sel = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    for (int item = 0; item < SV_COUNT; ++item) {
        wchar_t line[128];
        int price = ServicePrice(item, kServices[item].member ? who : -1);
        if (price < 0) swprintf(line, 128, L"%s\tnot sold to them", kServices[item].name);
        else if (!kServices[item].member) swprintf(line, 128, L"%s\t$%d  (whole family)", kServices[item].name, price);
        else swprintf(line, 128, L"%s\t$%d", kServices[item].name, price);
        SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)line);
    }
    sel = sel < 0 ? 0 : sel;
    SendMessageW(list, LB_SETCURSEL, sel, 0);
    SetDlgItemTextW(dlg, ID_SV_DESC, kServices[sel].what);
}

static INT_PTR CALLBACK ServicesProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG: {
        int stop = 130;
        SendMessageW(GetDlgItem(dlg, ID_SV_LIST), LB_SETTABSTOPS, 1, (LPARAM)&stop);
        HWND who = GetDlgItem(dlg, ID_SV_WHO);
        for (int i = 0; i < VillagerSlots; ++i) {
            if (!VillagerPresent(i) || Villager(i)[0x13578]) continue;
            wchar_t name[48];
            swprintf(name, 48, L"%.40hs", VillagerName(i));
            int row = (int)SendMessageW(who, LB_ADDSTRING, 0, (LPARAM)name);
            SendMessageW(who, LB_SETITEMDATA, row, i);
        }
        SendMessageW(who, LB_SETCURSEL, 0, 0);
        FillServices(dlg);
        return TRUE;
    }
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if ((id == ID_SV_WHO || id == ID_SV_LIST) && HIWORD(wp) == LBN_SELCHANGE) {
            FillServices(dlg);
        } else if (id == ID_SV_BUY) {
            int item = (int)SendMessageW(GetDlgItem(dlg, ID_SV_LIST), LB_GETCURSEL, 0, 0);
            if (item < 0 || item >= SV_COUNT) return TRUE;
            int who = kServices[item].member ? SelectedMember(dlg) : -1;
            const wchar_t *why = ServiceRefusal(item, who);
            int price = why ? -1 : ServicePrice(item, who);
            if (!why && price < 0) why = L"That is not sold to this family member.";
            if (!why && CurrentMoney() < price) why = L"You don't have enough money for that.";
            if (why) { Message(dlg, why); return TRUE; }
            wchar_t text[200];
            if (who >= 0) swprintf(text, 200, L"Buy %s for %.40hs for $%d?", kServices[item].name, VillagerName(who), price);
            else swprintf(text, 200, L"Buy %s for $%d?", kServices[item].name, price);
            if (!Confirm(dlg, text)) return TRUE;
            why = BuyService(item, who);
            if (why) { Message(dlg, why); FillServices(dlg); return TRUE; }
            if (item == SV_TIME_WARP) swprintf(text, 200, L"Time warp completed! It's 3 years later!");
            else swprintf(text, 200, L"Purchased: %s.", kServices[item].name);
            Message(dlg, text);
            FillServices(dlg);
        } else if (id == IDOK || id == IDCANCEL) {
            EndDialog(dlg, 0);
        }
        return TRUE;
    }
    case WM_CLOSE: EndDialog(dlg, 0); return TRUE;
    }
    return FALSE;
}

static void ShowServices(HWND owner) {
    static Template t;
    t.Begin(L"Services", 300, 226, 8);
    t.Item(STATIC, SS_LEFT, 10, 8, 280, 12, ID_SV_MONEY, L"");
    t.Item(STATIC, SS_LEFT, 10, 24, 90, 12, -1, L"Family member:");
    t.Item(LISTBOX, LBS_NOTIFY | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 10, 38, 90, 120, ID_SV_WHO, L"");
    t.Item(LISTBOX, LBS_NOTIFY | LBS_USETABSTOPS | WS_VSCROLL | WS_BORDER | WS_TABSTOP, 106, 24, 184, 106, ID_SV_LIST, L"");
    t.Item(STATIC, SS_LEFT, 106, 134, 184, 60, ID_SV_DESC, L"");
    t.Item(STATIC, SS_LEFT, 10, 166, 90, 24, -1, L"The price is for the family member picked.");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 10, 202, 75, 16, ID_SV_BUY, L"Buy");
    t.Item(BUTTON, BS_PUSHBUTTON | WS_TABSTOP, 215, 202, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, ServicesProc, 0);
}
