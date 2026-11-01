// family_page.inc -- the Upgrades menu's Family page. Included after family.inc.

enum { ID_FA_STATUS = 700, ID_FA_SAMESEX, ID_FA_REROLL, ID_FA_EMAIL, ID_FA_DIVORCE,
       ID_FA_FORCE, ID_FA_ANYGENDER, ID_FA_MALE, ID_FA_FEMALE, ID_FA_ANYCOUNT, ID_FA_SINGLE, ID_FA_TWINS,
       ID_FA_TRIPLETS, ID_FA_NAME, ID_FA_AGE, ID_FA_CHILD_BOY, ID_FA_CHILD_GIRL, ID_FA_ADOPT_BOY, ID_FA_ADOPT_GIRL,
       ID_FA_NEWPERSON, ID_FA_EVICT };
// gFamilyAction (vf1fun.cpp): ADOPT_EVICT or ADOPT_NEW_PERSON, carried out by the store once the dialogs close.

static void RefreshFamily(HWND dlg) {
    wchar_t s[200];
    int a = FounderSlot(), b = SpouseSlot();
    if (GameOver())
        swprintf(s, 200, L"Your family has been lost. You can adopt a new person.");
    else if (!CurrentFamily())
        swprintf(s, 200, L"There is no family yet.");
    else
        swprintf(s, 200, L"Family: %ls%ls%ls        Children: %d of %d%s", a >= 0 ? NameW(VillagerName(a), 0x19) : L"(gone)",
                 b >= 0 ? L" and " : L"", b >= 0 ? NameW(VillagerName(b), 0x19) : L"",
                 KidsChildren ? KidsChildren() : 6 - EmptyOffspringSlots(FamilyTree), KidsLimit ? KidsLimit() : 6,
                 Pregnant(a) || Pregnant(b) ? L"        Expecting" : L"");
    SetDlgItemTextW(dlg, ID_FA_STATUS, s);
    CheckDlgButton(dlg, ID_FA_SAMESEX, gVillage.sameSex ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(dlg, ID_FA_REROLL, gVillage.reroll ? BST_CHECKED : BST_UNCHECKED);
    CheckDlgButton(dlg, ID_FA_FORCE, (gVillage.armed & ARM_FORCE) ? BST_CHECKED : BST_UNCHECKED);
    int g = (gVillage.armed & ARM_MALE) ? ID_FA_MALE : (gVillage.armed & ARM_FEMALE) ? ID_FA_FEMALE : ID_FA_ANYGENDER;
    CheckRadioButton(dlg, ID_FA_ANYGENDER, ID_FA_FEMALE, g);
    int c = (gVillage.armed & ARM_SINGLE) ? ID_FA_SINGLE : (gVillage.armed & ARM_TWINS) ? ID_FA_TWINS
          : (gVillage.armed & ARM_TRIPLETS) ? ID_FA_TRIPLETS : ID_FA_ANYCOUNT;
    CheckRadioButton(dlg, ID_FA_ANYCOUNT, ID_FA_TRIPLETS, c);
    EnableWindow(GetDlgItem(dlg, ID_FA_NEWPERSON), GameOver());
}

static void ReadArmed(HWND dlg) {
    int m = 0;
    if (gFreeCheats && IsDlgButtonChecked(dlg, ID_FA_FORCE)) m |= ARM_FORCE;  // needs Free and Guaranteed Cheats
    if (IsDlgButtonChecked(dlg, ID_FA_MALE)) m |= ARM_MALE;
    if (IsDlgButtonChecked(dlg, ID_FA_FEMALE)) m |= ARM_FEMALE;
    if (IsDlgButtonChecked(dlg, ID_FA_SINGLE)) m |= ARM_SINGLE;
    if (IsDlgButtonChecked(dlg, ID_FA_TWINS)) m |= ARM_TWINS;
    if (IsDlgButtonChecked(dlg, ID_FA_TRIPLETS)) m |= ARM_TRIPLETS;
    gVillage.armed = m;
}

static void Report(HWND dlg, const wchar_t *problem, const wchar_t *done) {
    if (problem || done) Message(dlg, problem ? problem : done);
    RefreshFamily(dlg);
}

static INT_PTR CALLBACK FamilyProc(HWND dlg, UINT msg, WPARAM wp, LPARAM) {
    switch (msg) {
    case WM_INITDIALOG:
        SetDlgItemTextW(dlg, ID_FA_AGE, L"5");
        // the one name limit (in UTF-16 units: 300 characters are at most 1,200 units here; SetName cuts to 300)
        SendDlgItemMessageW(dlg, ID_FA_NAME, EM_LIMITTEXT, VF1_NAME_BOX_BYTES, 0);
        HideWithoutFreeCheats(dlg, ID_FA_FORCE);
        RefreshFamily(dlg);
        return TRUE;
    case WM_COMMAND: {
        int id = LOWORD(wp);
        wchar_t name[VF1_NAME_BOX_BYTES + 1];
        GetDlgItemTextW(dlg, ID_FA_NAME, name, VF1_NAME_BOX_BYTES + 1);
        switch (id) {
        case ID_FA_SAMESEX: gVillage.sameSex = IsDlgButtonChecked(dlg, id) == BST_CHECKED; break;
        case ID_FA_REROLL: gVillage.reroll = IsDlgButtonChecked(dlg, id) == BST_CHECKED; break;
        case ID_FA_FORCE: case ID_FA_ANYGENDER: case ID_FA_MALE: case ID_FA_FEMALE:
        case ID_FA_ANYCOUNT: case ID_FA_SINGLE: case ID_FA_TWINS: case ID_FA_TRIPLETS:
            ReadArmed(dlg);
            break;
        case ID_FA_EMAIL: Message(dlg, ForceMarriageEmail()); break;
        case ID_FA_DIVORCE:
            if (MessageBoxW(dlg, L"WARNING: this permanently removes the spouse from the Family Tree and the "
                            L"house. It cannot be undone.\n\nDivorce now?", L"Divorce Spouse",
                            MB_OKCANCEL | MB_ICONWARNING) == IDOK)
                Report(dlg, DivorceSpouse(), 0);  // the spouse simply goes away: no popup, no life event
            break;
        case ID_FA_CHILD_BOY: case ID_FA_CHILD_GIRL: {
            wchar_t age[8];
            GetDlgItemTextW(dlg, ID_FA_AGE, age, 8);
            Report(dlg, SpawnChild(id == ID_FA_CHILD_GIRL ? 1 : 0, _wtoi(age), name), 0);
            break;
        }
        case ID_FA_ADOPT_BOY: case ID_FA_ADOPT_GIRL: {
            wchar_t age[8];
            GetDlgItemTextW(dlg, ID_FA_AGE, age, 8);
            Report(dlg, AdoptOutsideChild(id == ID_FA_ADOPT_GIRL ? 1 : 0, _wtoi(age), name), 0);
            break;
        }
        case ID_FA_NEWPERSON:
            if (!GameOver()) { RefreshFamily(dlg); break; }
            gFamilyAction = ADOPT_NEW_PERSON;
            EndDialog(dlg, 0);
            break;
        case ID_FA_EVICT:
            if (MessageBoxW(dlg, L"This button will EVICT your current family and RESET the Family Tree. You will "
                            L"keep all the money, the house, the furnishings and everything you own.\n\nARE YOU SURE "
                            L"YOU WANT TO EVICT YOUR CURRENT FAMILY?\n\nClick OK to continue. Otherwise, click Cancel.",
                            L"Evict Family", MB_OKCANCEL | MB_ICONWARNING) == IDOK) {
                gFamilyAction = ADOPT_EVICT;
                EndDialog(dlg, 0);
            }
            break;
        case IDOK: case IDCANCEL: EndDialog(dlg, 0); break;
        }
        return TRUE;
    }
    case WM_CLOSE:
        EndDialog(dlg, 0);
        return TRUE;
    }
    return FALSE;
}

static void ShowFamily(HWND owner) {
    static Template t;
    const DWORD check = BS_AUTOCHECKBOX | WS_TABSTOP, radio = BS_AUTORADIOBUTTON, push = BS_PUSHBUTTON | WS_TABSTOP;
    t.Begin(L"Family: Marriage, Babies and Children", 300, 366, 29);
    t.Item(STATIC, SS_LEFT, 10, 8, 280, 12, ID_FA_STATUS, L"");
    t.Item(BUTTON, BS_GROUPBOX, 6, 24, 288, 62, -1, L"Marriage");
    t.Item(BUTTON, check, 14, 36, 260, 12, ID_FA_SAMESEX, L"Enable Same-Sex Marriage");
    t.Item(BUTTON, check, 14, 50, 260, 12, ID_FA_REROLL, L"Allow Reroll of Marriage Candidates (Reject shows another)");
    t.Item(BUTTON, push, 14, 65, 130, 16, ID_FA_EMAIL, L"Force Marriage Email");
    t.Item(BUTTON, push, 152, 65, 134, 16, ID_FA_DIVORCE, L"Divorce Spouse (spouse leaves)...");
    t.Item(BUTTON, BS_GROUPBOX, 6, 90, 288, 74, -1, L"Next pregnancy (stays set until a pregnancy succeeds)");
    t.Item(BUTTON, check, 14, 102, 200, 12, ID_FA_FORCE, L"Force Successful Pregnancy");
    t.Item(STATIC, SS_LEFT, 14, 118, 48, 12, -1, L"Babies:");
    t.Item(BUTTON, radio | WS_GROUP | WS_TABSTOP, 64, 118, 56, 12, ID_FA_ANYGENDER, L"Either");
    t.Item(BUTTON, radio, 122, 118, 56, 12, ID_FA_MALE, L"Male");
    t.Item(BUTTON, radio, 180, 118, 60, 12, ID_FA_FEMALE, L"Female");
    t.Item(STATIC, SS_LEFT | WS_GROUP, 14, 134, 48, 12, -1, L"How many:");
    t.Item(BUTTON, radio | WS_GROUP | WS_TABSTOP, 64, 134, 50, 12, ID_FA_ANYCOUNT, L"Any");
    t.Item(BUTTON, radio, 114, 134, 56, 12, ID_FA_SINGLE, L"Singleton");
    t.Item(BUTTON, radio, 172, 134, 48, 12, ID_FA_TWINS, L"Twins");
    t.Item(BUTTON, radio, 222, 134, 60, 12, ID_FA_TRIPLETS, L"Triplets");
    t.Item(STATIC, SS_LEFT | WS_GROUP, 14, 149, 274, 12, -1, L"Twins and triplets need free child places (6 per family).");
    // Each button that adds or removes a person says how, in brackets (the owner, 2026-11-01). Both Spawn rows
    // put the child straight into the house; no game event, e-mail or popup is shown:
    //   Spawn child in house          the couple's own child (their names as parents, an inherited look)
    //   Spawn outside child in house  a child from outside, adopted (no parents, the game's random look), as the
    //                                 game's own Little Visitor event's "Adopt" choice does, without its popup
    t.Item(BUTTON, BS_GROUPBOX, 6, 168, 288, 110, -1, L"Add children (age 2-13)");
    t.Item(STATIC, SS_LEFT, 14, 182, 88, 12, -1, L"Name (optional):");
    t.Item(EDIT, ES_LEFT | ES_AUTOHSCROLL | WS_BORDER | WS_TABSTOP | WS_GROUP, 104, 180, 100, 14, ID_FA_NAME, L"");
    t.Item(STATIC, SS_LEFT, 14, 200, 44, 12, -1, L"Age 2-13:");
    t.Item(EDIT, ES_LEFT | ES_NUMBER | WS_BORDER | WS_TABSTOP, 58, 198, 24, 14, ID_FA_AGE, L"");
    t.Item(BUTTON, push, 14, 216, 134, 16, ID_FA_CHILD_BOY, L"Spawn child in house (male)");
    t.Item(BUTTON, push, 152, 216, 134, 16, ID_FA_CHILD_GIRL, L"Spawn child in house (female)");
    t.Item(BUTTON, push, 14, 236, 272, 16, ID_FA_ADOPT_BOY, L"Spawn outside child in house (male)");
    t.Item(BUTTON, push, 14, 256, 272, 16, ID_FA_ADOPT_GIRL, L"Spawn outside child in house (female)");
    t.Item(BUTTON, BS_GROUPBOX, 6, 282, 288, 56, -1, L"Start again");
    t.Item(BUTTON, push, 14, 296, 272, 16, ID_FA_NEWPERSON, L"Adopt New Person (the game's Adoption screen; after a game over)");
    t.Item(BUTTON, push, 14, 316, 272, 16, ID_FA_EVICT, L"Evict Family (everyone leaves the house)...");
    t.Item(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 219, 344, 75, 16, IDOK, L"Close");
    DialogBoxIndirectParamW(Module, t.Get(), owner, FamilyProc, 0);
}
