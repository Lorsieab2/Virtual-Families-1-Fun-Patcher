// features.inc -- included by vf1fun.cpp after the dialogs' helpers.
//
// Everything here follows the owner's rule: DLLs over cave space. The game
// executable only carries the loader; every hook below is installed at run
// time by this DLL, and only after the bytes it replaces have been checked
// against the vanilla game (see data/vf1_verified.json and research notes).

// ---------------------------------------------------------------- patching helpers
static bool BytesAre(unsigned address, const unsigned char *expected, int n) {
    return memcmp((void *)address, expected, n) == 0;
}

static bool WriteCode(unsigned address, const void *bytes, int n) {
    DWORD old;
    if (!VirtualProtect((void *)address, n, PAGE_EXECUTE_READWRITE, &old))
        return false;
    memcpy((void *)address, bytes, n);
    VirtualProtect((void *)address, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void *)address, n);
    return true;
}

// Replace `n` verified bytes at `site` with a jump to `target` (NOP-padded).
static bool InstallJump(unsigned site, const unsigned char *expected, int n, void *target) {
    if (!BytesAre(site, expected, n)) {
        unsigned char jmp = 0xE9;
        if (*(unsigned char *)site == jmp &&
            site + 5 + *(int *)(site + 1) == (unsigned)target)
            return true;  // already installed
        return false;
    }
    unsigned char patch[16];
    patch[0] = 0xE9;
    *(int *)(patch + 1) = (int)((unsigned)target - (site + 5));
    for (int i = 5; i < n; ++i) patch[i] = 0x90;
    return WriteCode(site, patch, n);
}

// ---------------------------------------------------------------- per-village state
// Things the game does not save (the bought purchases, Food Club's last
// delivery, the price multiplier) are kept per save slot in
// "Documents\LDW\<exe name>\Virtual Families 1 Patcher Data\Slot N.ini",
// next to the game's own save. Loaded after theGameState::Load(slot) and
// written after theGameState::Save(slot); cleared when a new village starts.
struct VillageState {
    int brokerage, foodClub, healthPlan, luckyRock, maid, gardener;
    int priceMultiplier;          // 1, 2, 5 or 100
    unsigned foodClubLast;        // CGameTime::Seconds of the last delivery
    int sameSex, reroll;          // Enable Same-Sex Marriage, Allow Reroll of Marriage Candidates
    int armed;                    // pregnancy one-shots (family.inc ARM_*)
};
static VillageState gVillage = { 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0 };
static int gAdoptionMode;         // family.inc: an Evict or Adopt New Person in progress

typedef unsigned (__thiscall *SecondsFn)(void *time);
static const SecondsFn GameSeconds = (SecondsFn)0x422320;  // CGameTime::Seconds
static void *const GameTime = (void *)0x50C5D0;

static int CurrentSlot() { return *(int *)((unsigned char *)GameStateGet() + 0x1B188); }

static bool SidecarPath(int slot, wchar_t *out, int cap) {
    wchar_t docs[MAX_PATH], exe[MAX_PATH];
    if (FAILED(SHGetFolderPathW(0, CSIDL_PERSONAL, 0, 0, docs)))
        return false;
    GetModuleFileNameW(0, exe, MAX_PATH);
    wchar_t *name = wcsrchr(exe, L'\\');
    name = name ? name + 1 : exe;
    wchar_t *dot = wcsrchr(name, L'.');
    if (dot) *dot = 0;
    swprintf(out, cap, L"%s\\LDW\\%s\\Virtual Families 1 Patcher Data", docs, name);
    CreateDirectoryW(out, 0);
    size_t len = wcslen(out);
    swprintf(out + len, cap - len, L"\\Slot %d.ini", slot);
    return true;
}

static void LoadVillageState(int slot) {
    wchar_t path[1024];
    VillageState v = { 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0 };
    if (SidecarPath(slot, path, 1024)) {
        v.brokerage = GetPrivateProfileIntW(L"Village", L"BrokerageAccount", 0, path);
        v.foodClub = GetPrivateProfileIntW(L"Village", L"FoodClub", 0, path);
        v.healthPlan = GetPrivateProfileIntW(L"Village", L"HealthPlan", 0, path);
        v.luckyRock = GetPrivateProfileIntW(L"Village", L"LuckyRock", 0, path);
        v.maid = GetPrivateProfileIntW(L"Village", L"Maid", 0, path);
        v.gardener = GetPrivateProfileIntW(L"Village", L"Gardener", 0, path);
        v.priceMultiplier = GetPrivateProfileIntW(L"Village", L"PriceMultiplier", 1, path);
        v.foodClubLast = (unsigned)GetPrivateProfileIntW(L"Village", L"FoodClubLastDelivery", 0, path);
        v.sameSex = GetPrivateProfileIntW(L"Village", L"SameSexMarriage", 0, path);
        v.reroll = GetPrivateProfileIntW(L"Village", L"RerollMarriageCandidates", 0, path);
        v.armed = GetPrivateProfileIntW(L"Village", L"NextPregnancy", 0, path) & 63;
    }
    if (v.priceMultiplier != 2 && v.priceMultiplier != 5 && v.priceMultiplier != 100)
        v.priceMultiplier = 1;
    gVillage = v;
}

static void SaveVillageState(int slot) {
    wchar_t path[1024], s[32];
    if (!SidecarPath(slot, path, 1024))
        return;
    struct { const wchar_t *key; unsigned value; } rows[] = {
        { L"BrokerageAccount", (unsigned)gVillage.brokerage }, { L"FoodClub", (unsigned)gVillage.foodClub },
        { L"HealthPlan", (unsigned)gVillage.healthPlan }, { L"LuckyRock", (unsigned)gVillage.luckyRock },
        { L"Maid", (unsigned)gVillage.maid }, { L"Gardener", (unsigned)gVillage.gardener },
        { L"PriceMultiplier", (unsigned)gVillage.priceMultiplier }, { L"FoodClubLastDelivery", gVillage.foodClubLast },
        { L"SameSexMarriage", (unsigned)gVillage.sameSex }, { L"RerollMarriageCandidates", (unsigned)gVillage.reroll },
        { L"NextPregnancy", (unsigned)gVillage.armed },
    };
    for (int i = 0; i < (int)(sizeof rows / sizeof rows[0]); ++i) {
        swprintf(s, 32, L"%u", rows[i].value);
        WritePrivateProfileStringW(L"Village", rows[i].key, s, path);
    }
}

static void ApplyVillageEffects();

typedef bool (__thiscall *SlotFn)(void *state, int slot);
static SlotFn OriginalGameStateLoad, OriginalGameStateSave;
static unsigned *const GameStateVtable = (unsigned *)0x4B5E50;  // RTTI theGameState; Load slot +0x18, Save slot +0x1C

// theGameState::Load(slot): at startup the game loads slots 1-5 one after
// another to read their family names, then the current one, so the last
// successful load wins -- which is the village being played.
static bool __fastcall GameStateLoad(void *state, void *, int slot) {
    bool ok = OriginalGameStateLoad(state, slot);
    if (ok && slot >= 1 && slot <= 5) {
        gAdoptionMode = 0;
        LoadVillageState(slot);
        ApplyVillageEffects();
    }
    return ok;
}

// theGameState::Save(slot): slots 21+ are the game's backup copies.
static bool __fastcall GameStateSave(void *state, void *, int slot) {
    bool ok = OriginalGameStateSave(state, slot);
    if (ok && slot >= 1 && slot <= 5)
        SaveVillageState(slot);
    return ok;
}

// theGameState::Init (0x424110) resets everything for a new village (Start
// Over, new player). It is not virtual; its callers are retargeted to this
// wrapper, which clears the per-village state before the game's own reset.
typedef void (__thiscall *VoidThisFn)(void *self);
static const VoidThisFn GameStateInit = (VoidThisFn)0x424110;
static void __fastcall GameStateInitWrapper(void *state, void *) {
    gVillage = VillageState();
    gVillage.priceMultiplier = 1;
    gAdoptionMode = 0;
    ApplyVillageEffects();
    GameStateInit(state);
}

static void RetargetCallsTo(unsigned target, void *replacement) {
    // Every `call rel32` in .text that reaches target.
    unsigned char *p = (unsigned char *)0x401000, *end = (unsigned char *)(0x401000 + 0xB0B59 - 5);
    for (; p < end; ++p) {
        if (*p == 0xE8 && (unsigned)(p + 5) + *(int *)(p + 1) == target) {
            int rel = (int)((unsigned)replacement - (unsigned)(p + 5));
            WriteCode((unsigned)(p + 1), &rel, 4);
        }
    }
}

// ---------------------------------------------------------------- store prices
// CInventoryManager::GetPrice (0x4968C0) and CTech::GetPrice (0x4229D0) are
// the only readers of the store's prices: the store label, the buy dialog
// (whose value Buy charges) and the return-to-store refund. Replacing both
// keeps label, charge and refund consistent. Health Plan: medicines (items
// 20-29) at a quarter of the price, as in VF2.
static int __fastcall ItemPrice(void *, void *, int item) {
    if (item < 1 || item > 0x50)
        return 0;
    int price = *(int *)(0x4FE19C + item * 32);
    if (gVillage.healthPlan && item >= 20 && item <= 29)
        price /= 4;
    return price * gVillage.priceMultiplier;
}

static int __fastcall TechPrice(void *, void *, int tech, int level) {
    if (level < 1 || level > 3)
        return 0;
    return *(int *)(0x4EF620 + 4 * (tech * 3 + level)) * gVillage.priceMultiplier;
}

// ---------------------------------------------------------------- Lucky Rock
// CCollectableItem::Add's rarity roll: rare if rand(100) < 4, else uncommon if
// < 17. VF2's Lucky Rock doubles both: 8 and 34.
static void ApplyLuckyRock() {
    unsigned char rare = gVillage.luckyRock ? 8 : 4, either = gVillage.luckyRock ? 34 : 17;
    unsigned char *a = (unsigned char *)0x414B6F, *b = (unsigned char *)0x414B7C;
    if ((a[-2] == 0x83 && a[-1] == 0xF8) && (b[-2] == 0x83 && b[-1] == 0xF8)) {
        if (*a != rare) WriteCode((unsigned)a, &rare, 1);
        if (*b != either) WriteCode((unsigned)b, &either, 1);
    }
}

// ---------------------------------------------------------------- bank
static float gCheatInterestPercent = -1.f;  // the Cheat Upgrades rate, if set
static void ApplyEffectiveInterest() {
    float base = gCheatInterestPercent >= 0 ? gCheatInterestPercent : 10.f;
    // VF2's Brokerage Account: +2 points, at most 11%.
    if (gVillage.brokerage && gCheatInterestPercent < 0)
        base = base + 2 > 11 ? 11 : base + 2;
    ApplyInterestRate(base);
}

static void CheatInterestChanged(float percent) {
    gCheatInterestPercent = percent;
    ApplyEffectiveInterest();
}

static void ApplyVillageEffects() {
    ApplyLuckyRock();
    ApplyEffectiveInterest();
}

// ---------------------------------------------------------------- house mess
typedef void (__thiscall *CountFn)(void *self, int n);
typedef void (__thiscall *RemoveAllFn)(void *self, int type);
typedef ldwPoint *(__thiscall *SpawnPosFn)(void *map, ldwPoint *out, int material);
static unsigned char *const Collectables = (unsigned char *)0x501858;
static const CountFn SpawnWeedsInYard = (CountFn)0x413DC0;
static const RemoveAllFn RemoveAll = (RemoveAllFn)0x413B80;
static const SpawnPosFn GetRandomSpawnPos = (SpawnPosFn)0x492A30;
static void *const ContentMap = (void *)0x8352E0;

static void CleanHouse() {  // the stock Housekeeping Services event's four categories
    RemoveAll(Collectables, 0x7E); RemoveAll(Collectables, 0x84);
    RemoveAll(Collectables, 0x8C); RemoveAll(Collectables, 0x8E);
}
static void CleanGarden() { RemoveAll(Collectables, 0x88); }

// One piece of house mess, exactly as CCollectableItem::SpawnTrashInHouse
// (0x413D40) fills a slot, for any type. Socks get a never-expiring +8:
// Update (0x414C75) wrongly removes an expired type 0x7E the next frame.
static bool SpawnMess(int type, int counterOffset, int material) {
    unsigned char *slot = Collectables + 4;
    for (int i = 0; i < 30; ++i, slot += 0x1C) {
        if (slot[0])
            continue;
        slot[0] = 1;
        *(int *)(slot + 0x14) = -1;
        *(int *)(slot + 4) = type;
        *(unsigned *)(slot + 8) = 0xFFFFFFFF;
        *(int *)(slot + 0x18) = 0;
        *(int *)(Collectables + counterOffset) += 1;
        ldwPoint p;
        GetRandomSpawnPos(ContentMap, &p, material);
        *(int *)(slot + 0xC) = p.x;
        *(int *)(slot + 0x10) = p.y;
        return true;
    }
    return false;  // all 30 mess slots are full
}

static int gMessCycle;
// VF2: "Spawns 15: 5 dirt smudges, 5 socks, 5 wrappers", cycling every sub-type.
static int FillHouseWithTrash() {
    int made = 0;
    for (int i = 0; i < 5; ++i) {
        int c = gMessCycle++;
        if (!SpawnMess(0x8E + c % 3, 0x704, 7)) return made; ++made;   // smudges
        if (!SpawnMess(0x7E + c % 6, 0x6F8, 7)) return made; ++made;   // socks
        if (!SpawnMess(0x84 + c % 4, 0x700, 7)) return made; ++made;   // wrappers
    }
    return made;
}
static int gWeedCycle;
static int FillYardWithWeeds() {
    int made = 0;
    for (int i = 0; i < 15; ++i) {
        if (!SpawnMess(0x88 + gWeedCycle++ % 4, 0x6FC, 2)) break;
        ++made;
    }
    return made;
}

// ---------------------------------------------------------------- achievements and collections
typedef void (__thiscall *IdFn)(void *self, int id);
static void *const Achievements = (void *)0x5008D8;
static const IdFn SetComplete = (IdFn)0x413170;
static const IdFn ResetProgressIfIncomplete = (IdFn)0x412CE0;
static const VoidThisFn ResetAllAchievements = (VoidThisFn)0x413100;
static const VoidThisFn ResetCollectionCounts = (VoidThisFn)0x413A00;

static void CompleteAllAchievements() {
    for (int id = 0; id <= 0x64; ++id) SetComplete(Achievements, id);
}
static void ResetCollections() {  // as The Mysterious Collector event does
    ResetCollectionCounts(Collectables);
    for (int id = 0x51; id <= 0x54; ++id) ResetProgressIfIncomplete(Achievements, id);
}
static void CompleteCollections() {
    int *counts = (int *)(Collectables + 0x5E0);
    for (int i = 0; i < 0x30; ++i) if (counts[i] < 1) counts[i] = 1;
    for (int id = 0x51; id <= 0x55; ++id) SetComplete(Achievements, id);
}

// ---------------------------------------------------------------- Older Villager Mortality Curve
// VF2's .vf2mort curve, unchanged: the yearly old-age chance is
// 1 - exp(-(0.00365 * years past 55 + 0.06 * years past 110)), in millionths
// (rounded half up, capped at 999999), at an effective age of
// age - min(active food groups, 4). It replaces only VF1's stock old-age roll
// (0x48BFC6..0x48C073: 10% per year past 55 + bonuses, certain death 10 years
// on). Other causes of death are untouched.
static int gMortalityTable[318];
static bool gMortalityOn;
static void BuildMortalityTable() {
    for (int age = 0; age < 318; ++age) {
        int past = age > 55 ? age - 55 : 0, late = age > 110 ? age - 110 : 0;
        double hazard = -expm1(-(0.00365 * past + 0.06 * late));
        int t = (int)floor(hazard * 1000000 + 0.5);
        gMortalityTable[age] = t > 999999 ? 999999 : t;
    }
}
extern "C" int __cdecl VF1RollMortality(int tick, int foodGroups) {
    if (tick < 0 || tick % 20 != 0) return 0;
    if (foodGroups < 0) foodGroups = 0;
    if (foodGroups > 4) foodGroups = 4;
    int effective = tick / 20 - foodGroups;
    if (effective < 55) return 0;
    int hazard = effective <= 317 ? gMortalityTable[effective] : 999999;
    return GetRandom(1000000) < hazard ? 1 : 0;
}

// Entered by a jmp at 0x48BFC6 (`mov ecx,ebx; call 0x48FE30`, 7 bytes) inside
// the physiology upkeep: ebx = CVillagerState*, [ebx+8] = the tick (age)
// being processed.
__declspec(naked) static void MortalityDetour() {
    __asm {
        mov ecx, ebx
        mov eax, 0x48FE30          // CVillagerState::FoodGroupsActive
        call eax
        cmp byte ptr [gMortalityOn], 0
        jne curve
        push 0x48BFCD              // stock roll continues with eax = food groups
        ret
    curve:
        push eax
        push dword ptr [ebx + 8]
        call VF1RollMortality
        add esp, 8
        test eax, eax
        jz survive
        push 2                     // cause: old age
        push 0                     // health 0
        mov ecx, ebx
        mov eax, 0x48F820          // CVillagerState::SetHealth
        call eax
    survive:
        push 0x48C073              // end of the stock old-age block
        ret
    }
}

// ---------------------------------------------------------------- time warp
// Entered by a jmp at 0x489E8C (`mov ecx,edi; mov ebx,eax; push ebx;
// call 0x4897F0`, 10 bytes) in CVillagerManager::AllVillagersTimeflowUpkeep:
// eax = the ticks to add to this villager, edi = &age, esi = villager+0x13578.
// Queued warp ticks are added once to each living villager, through the
// game's own IncrementAge, so leaving home and the oldest-ever record still
// run (research: never write the age directly).
static int gWarpTicks;
static unsigned gWarpPending;  // bit i: villager i still to receive this warp
static void StartTimeWarp(int ticks) {
    gWarpPending = 0;
    for (int i = 0; i < 30; ++i) {
        unsigned char *v = (unsigned char *)0x5B8898 + 0x14640 + i * 0x145FC;
        if (v[0x13574] && !v[0x13578] && *(int *)(v + 0x2AE0) > 0)
            gWarpPending |= 1u << i;
    }
    gWarpTicks = gWarpPending ? ticks : 0;
}
extern "C" int __cdecl VF1WarpTicks(unsigned char *goneByte, int ticks) {
    if (!gWarpTicks)
        return ticks;
    unsigned char *villager = goneByte - 0x13578;
    unsigned offset = (unsigned)(villager - ((unsigned char *)0x5B8898 + 0x14640));
    if (offset % 0x145FC != 0 || offset / 0x145FC >= 30)
        return ticks;
    unsigned bit = 1u << (offset / 0x145FC);
    if (!(gWarpPending & bit))
        return ticks;
    gWarpPending &= ~bit;
    int warp = gWarpTicks;
    if (!gWarpPending)
        gWarpTicks = 0;
    return ticks + warp;
}
__declspec(naked) static void WarpDetour() {
    __asm {
        mov ebx, eax               // native ticks stay in ebx for the remainder sum
        push eax
        push esi
        call VF1WarpTicks
        add esp, 8
        mov ecx, edi
        push eax
        mov eax, 0x4897F0          // IncrementAge
        call eax
        push 0x489E96
        ret
    }
}

// ---------------------------------------------------------------- game speed and pause
typedef void (__thiscall *SetSpeedFn)(void *time, int speed);
static const SetSpeedFn SetSpeed = (SetSpeedFn)0x422450;
static int *GameSpeedSlot() { return (int *)((unsigned char *)GameStateGet() + 0x1B180); }
static bool GamePaused() { return *GameSpeedSlot() >= 999; }
static void PauseGame() {           // as the Space bar does (0x440CB2)
    if (GamePaused()) return;
    SetSpeed(GameTime, 999);
    *GameSpeedSlot() += 999;
}
static void ResumeGame() {
    if (!GamePaused()) return;
    int s = *GameSpeedSlot() - 999;
    if (s <= 0) s = 10;
    SetSpeed(GameTime, s);
    *GameSpeedSlot() = s;
}
// Speed: CGameTime runs at 10/speed, so 5 is 2x, 2 is 5x and 1 is 10x.
static int gWantedSpeed = 10;
static void ApplyGameSpeed() {
    if (GamePaused() || *GameSpeedSlot() == gWantedSpeed) return;
    SetSpeed(GameTime, gWantedSpeed);
    *GameSpeedSlot() = gWantedSpeed;
}

// ---------------------------------------------------------------- per-frame work
static DWORD gLastHelperTick;
static void FeaturesTick() {
    unsigned char *state = (unsigned char *)GameStateGet();
    if (!state || *(int *)(state + 0x1B300) != 0)   // main scene only
        return;
    if (gWantedSpeed != 10) ApplyGameSpeed();
    DWORD now = GetTickCount();
    if (now - gLastHelperTick < 15000)               // every 15 real seconds
        return;
    gLastHelperTick = now;
    if (gVillage.maid) CleanHouse();
    if (gVillage.gardener) CleanGarden();
    if (gVillage.foodClub) {                         // 500 food every game day
        unsigned t = GameSeconds(GameTime);
        if (gVillage.foodClubLast == 0 || t < gVillage.foodClubLast)
            gVillage.foodClubLast = t;
        while (t - gVillage.foodClubLast >= 86400) {
            FoodAdjust(Food, 500);
            gVillage.foodClubLast += 86400;
        }
    }
}

// ---------------------------------------------------------------- installation
static const unsigned char kItemPriceBytes[] = { 0x8B, 0x44, 0x24, 0x04, 0x8D, 0x48, 0xFF };
static const unsigned char kTechPriceBytes[] = { 0x8B, 0x4C, 0x24, 0x08, 0x8D, 0x41, 0xFF };
static const unsigned char kMortalityBytes[] = { 0x8B, 0xCB, 0xE8, 0x63, 0x3E, 0x00, 0x00 };
static const unsigned char kWarpBytes[] = { 0x8B, 0xCF, 0x8B, 0xD8, 0x53, 0xE8, 0x5A, 0xF9, 0xFF, 0xFF };

static void InstallFeatureHooks() {
    BuildMortalityTable();
    gMortalityOn = SettingOn(L"OlderVillagerMortalityCurve", true);
    InstallJump(0x48BFC6, kMortalityBytes, 7, (void *)&MortalityDetour);
    InstallJump(0x489E8C, kWarpBytes, 10, (void *)&WarpDetour);
    InstallJump(0x4968C0, kItemPriceBytes, 7, (void *)&ItemPrice);
    InstallJump(0x4229D0, kTechPriceBytes, 7, (void *)&TechPrice);
    HookVtableSlot(GameStateVtable + 6, (void *)&GameStateLoad, (unsigned *)&OriginalGameStateLoad);
    HookVtableSlot(GameStateVtable + 7, (void *)&GameStateSave, (unsigned *)&OriginalGameStateSave);
    RetargetCallsTo(0x424110, (void *)&GameStateInitWrapper);
}
