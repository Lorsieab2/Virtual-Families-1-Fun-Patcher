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
    unsigned achievements;        // patcher_achievements.inc: one bit per unlocked milestone
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
        v.achievements = (unsigned)GetPrivateProfileIntW(L"Village", L"PatcherAchievements", 0, path) & 0xFFF;
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
        { L"NextPregnancy", (unsigned)gVillage.armed }, { L"PatcherAchievements", gVillage.achievements },
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
static void NormalSpeedForSaveFile(bool restoreAfter);
static bool __fastcall GameStateLoad(void *state, void *, int slot) {
    bool ok = OriginalGameStateLoad(state, slot);
    if (ok) NormalSpeedForSaveFile(false);  // a saved village always comes back at normal speed
    if (ok && slot >= 1 && slot <= 5) {
        gAdoptionMode = 0;
        LoadVillageState(slot);
        ApplyVillageEffects();
    }
    return ok;
}

// theGameState::Save(slot): slots 21+ are the game's backup copies.
static int gSpeedBeforeSave;
static bool __fastcall GameStateSave(void *state, void *, int slot) {
    NormalSpeedForSaveFile(true);  // never write a Time Controls speed into the save
    bool ok = OriginalGameStateSave(state, slot);
    if (gSpeedBeforeSave) { *(int *)((unsigned char *)state + 0x1B180) = gSpeedBeforeSave; gSpeedBeforeSave = 0; }
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

// A bag of organic groceries adds 250 food to the fridge (items 8-11, 0x446E4D:
// `mov edi, 0xFA`); plain groceries add 150. Food Club delivers all four organic types a day
// ("bags of organic, local groceries containing all 4 food groups", as in VF2).
static const int kOrganicBagFood = 250;
static const int kFoodClubDelivery = 4 * kOrganicBagFood;  // all four organic types (items 8-11), one of each food group

// ---------------------------------------------------------------- store prices
// CInventoryManager::GetPrice (0x4968C0) and CTech::GetPrice (0x4229D0) are
// the only readers of the store's prices: the store label, the buy dialog
// (whose value Buy charges) and the return-to-store refund. Replacing both
// keeps label, charge and refund consistent. Health Plan: medicines (items
// VF2ApplyPriceMultiplier: the multiplied price stops at 2,147,483,647 instead of wrapping.
static int SaturatedPrice(int price) {
    if (price <= 0 || gVillage.priceMultiplier == 1) return price;
    __int64 r = (__int64)price * gVillage.priceMultiplier;
    return r > 0x7FFFFFFF ? 0x7FFFFFFF : (int)r;
}
// 20-29) at a quarter of the price, as in VF2.
static int __fastcall ItemPrice(void *, void *, int item) {
    if (item < 1 || item > 0x50)
        return 0;
    int price = *(int *)(0x4FE19C + item * 32);
    if (gVillage.healthPlan && item >= 20 && item <= 29)
        price /= 4;
    if (gVillage.foodClub && item >= 4 && item <= 11)  // Food Club: half price on groceries (items 4-11)
        price /= 2;
    return SaturatedPrice(price);
}

static int __fastcall TechPrice(void *, void *, int tech, int level) {
    if (level < 1 || level > 3)
        return 0;
    return SaturatedPrice(*(int *)(0x4EF620 + 4 * (tech * 3 + level)));
}

// ---------------------------------------------------------------- Lucky Rock
// CCollectableItem::Add's rarity roll: rare if rand(100) < 4, else uncommon if
// < 17. VF2's Lucky Rock doubles both: 8 and 34.
// ... and doubles the spawn attempt rate, as VF2's does (3/6600 -> 3/3300): CCollectableItem::Update's
// `push 6600; call GetRandom; cmp eax, 3` (0x414DF4, the immediate at 0x414DF5).
static void ApplyLuckyRock() {
    static const unsigned char stock[5] = { 0x68, 0xC8, 0x19, 0x00, 0x00 };    // push 6600
    static const unsigned char doubled[5] = { 0x68, 0xE4, 0x0C, 0x00, 0x00 };  // push 3300
    unsigned char *spawn = (unsigned char *)0x414DF4;
    const unsigned char *want = gVillage.luckyRock ? doubled : stock;
    if ((memcmp(spawn, stock, 5) == 0 || memcmp(spawn, doubled, 5) == 0) && memcmp(spawn, want, 5) != 0)
        WriteCode(0x414DF4, want, 5);
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

// The speed slot is part of the saved game (theGameState +0x1B180), and the game catches up on the time it
// was closed at that speed: a village saved at 10x aged 26 years in the 10.6 hours it was closed (live
// 2026-10-11) and its people died of the neglect. So a Time Controls speed never reaches the save file:
// it is written at normal speed (paused stays paused), and a save that already holds one (written by an
// earlier version) loads at normal speed. Only the stock values 10 and 999+10 are left alone.
static void NormalSpeedForSaveFile(bool restoreAfter) {
    if (!GameStateGet()) return;
    int *slot = GameSpeedSlot();
    int s = *slot, paused = s >= 999 ? 999 : 0, speed = s - paused;
    if (speed == 10) return;
    if (restoreAfter) gSpeedBeforeSave = s;
    else { gWantedSpeed = 10; if (!paused) SetSpeed(GameTime, 10); }
    *slot = paused + 10;
}
static void ApplyGameSpeed() {
    if (GamePaused() || *GameSpeedSlot() == gWantedSpeed) return;
    SetSpeed(GameTime, gWantedSpeed);
    *GameSpeedSlot() = gWantedSpeed;
}

// ---------------------------------------------------------------- Power Failure (Fix Vanilla Game Bugs)
// FIX: "KEEP THE FOOD" ALWAYS SAYS IT WAS FINE.
// CEventThePowerFailure (vtable 0x4B594C): choice B ("keep the food") makes
// GetRandom(GetRandom(4)) random villagers sick (ImpactGame 0x4198E0), but its
// result text (GetResultDescription 0x4198C0) is always 0x5E7 "This stuff
// still looks okay." -- 0x5E8 "Everyone gets an upset stomach. The food was
// not ok." is never shown. The island-event dialog asks for the text when a
// choice is clicked (0x41B144) and applies ImpactGame on OK (0x41B0D1), so the
// roll is made here when the text is asked for, with the game's own
// distribution, and ImpactGame applies exactly that roll. The dialog's
// layout pass (0x41AC68 / 0x41ACA0) gets the longer text so it always fits.
typedef int (__thiscall *ChoiceFn)(void *event, int choice);
typedef int (__thiscall *RandomVillagerFn)(void *manager, int flag);
typedef void (__thiscall *SymptomFn)(void *state, int symptom);
static unsigned *const PowerFailureVtable = (unsigned *)0x4B594C;
static const unsigned PowerFailureShowText = 0x41B14A;  // return address of the click-time call
static const RandomVillagerFn RandomVillager = (RandomVillagerFn)0x48A490;
static const SymptomFn SetSymptom = (SymptomFn)0x48FD80;
static ChoiceFn OriginalPowerFailureImpact;
static int gPowerFailureSick = -1;  // -1: no roll made for the choice on screen

static int __fastcall PowerFailureText(void *, void *, int choice) {
    if (choice == 0) return 0x5E6;
    if ((unsigned)_ReturnAddress() != PowerFailureShowText) return 0x5E8;
    gPowerFailureSick = GetRandom(GetRandom(4));
    return gPowerFailureSick > 0 ? 0x5E8 : 0x5E7;
}

static int __fastcall PowerFailureImpact(void *event, void *, int choice) {
    if (choice == 0 || gPowerFailureSick < 0)
        return OriginalPowerFailureImpact(event, choice);
    int sick = gPowerFailureSick;
    gPowerFailureSick = -1;
    typedef void (__thiscall *PropFn)(void *environment, int prop);
    ((PropFn)0x4938C0)((void *)0x8752F0, 0x16);  // CEnvironment::SetProp, as ImpactGame
    for (int i = 0; i < sick; ++i) {
        int slot = RandomVillager(VillagerManager, 0);
        if (slot < 0 || slot >= VillagerSlots) break;
        SetSymptom(Villager(slot) + 0x2AD4, 2);
    }
    return 0;
}

static void InstallPowerFailureFix() {
    unsigned *text = PowerFailureVtable + 11, *impact = PowerFailureVtable + 12;
    if (*text != 0x4198C0 && *text != (unsigned)&PowerFailureText) return;
    if (*impact != 0x4198E0 && *impact != (unsigned)&PowerFailureImpact) return;
    unsigned unused;
    HookVtableSlot(text, (void *)&PowerFailureText, &unused);
    HookVtableSlot(impact, (void *)&PowerFailureImpact, (unsigned *)&OriginalPowerFailureImpact);
}

// ---------------------------------------------------------------- per-frame work
static void CheckAchievements();  // patcher_achievements.inc
// Clamp Money and Food: the Virtual Families 2 maximums (vf1fun.cpp, kMaxMoney / kMaxFood).
// Food is never legitimately negative (CFoodStore::Adjust floors it at 0), so a negative
// value can only be an overflow past 2^31 and is put back to the maximum.
static bool gClampResources;
static void ClampResources() {
    float *money = (float *)Money;
    if (*money > 4000000000.f) *money = 4000000000.f;
    if (*Food < 0) *Food = 2147483647;
}
static DWORD gLastHelperTick;
static void FeaturesTick() {
    if (gClampResources) ClampResources();
    unsigned char *state = (unsigned char *)GameStateGet();
    if (!state || *(int *)(state + 0x1B300) != 0)   // main scene only
        return;
    if (gWantedSpeed != 10) ApplyGameSpeed();
    DWORD now = GetTickCount();
    if (now - gLastHelperTick < 15000)               // every 15 real seconds
        return;
    gLastHelperTick = now;
    CheckAchievements();
    if (gVillage.maid) CleanHouse();
    if (gVillage.gardener) CleanGarden();
    if (gVillage.foodClub) {                         // one organic bag (250 food) every game day
        unsigned t = GameSeconds(GameTime);
        if (gVillage.foodClubLast == 0 || t < gVillage.foodClubLast)
            gVillage.foodClubLast = t;
        while (t - gVillage.foodClubLast >= 86400) {
            AddFoodSaturating(kFoodClubDelivery);
            gVillage.foodClubLast += 86400;
        }
    }
}

// ---------------------------------------------------------------- installation
static const unsigned char kItemPriceBytes[] = { 0x8B, 0x44, 0x24, 0x04, 0x8D, 0x48, 0xFF };
static const unsigned char kTechPriceBytes[] = { 0x8B, 0x4C, 0x24, 0x08, 0x8D, 0x41, 0xFF };
static const unsigned char kMortalityBytes[] = { 0x8B, 0xCB, 0xE8, 0x63, 0x3E, 0x00, 0x00 };
static const unsigned char kWarpBytes[] = { 0x8B, 0xCF, 0x8B, 0xD8, 0x53, 0xE8, 0x5A, 0xF9, 0xFF, 0xFF };

// ---------------------------------------------------------------- Private Adult Romantic Time
// Dropping one adult on another (theMainScene pairing, 0x441070..): when the
// family has no room for children (0x48AC80 = EmptyOffspringSlots > 0 is false)
// and the two adults are of different genders, the stock code says "They have
// enough kids already!" (0x3DB) and refuses. The jump at 0x441287 (`je 0x4412C7`,
// taken for same-gender pairs) becomes unconditional, so every adult pair runs
// the ordinary romantic sequence with its stock cooldown (the Virtual Families 2
// patcher's "six-child private romantic time"). No baby results: Impregnate
// refuses when there is no free child place.
static void InstallPrivateRomanticTime() {
    static const unsigned char stock[] = { 0x74, 0x3E }, patched[] = { 0xEB, 0x3E };
    if (BytesAre(0x441287, stock, 2))
        WriteCode(0x441287, patched, 2);
}

static void InstallFeatureHooks() {
    BuildMortalityTable();
    gMortalityOn = SettingOn(L"OlderVillagerMortalityCurve", true);
    if (SettingOn(L"PrivateRomanticTime", true))
        InstallPrivateRomanticTime();
    InstallJump(0x48BFC6, kMortalityBytes, 7, (void *)&MortalityDetour);
    InstallJump(0x489E8C, kWarpBytes, 10, (void *)&WarpDetour);
    InstallJump(0x4968C0, kItemPriceBytes, 7, (void *)&ItemPrice);
    InstallJump(0x4229D0, kTechPriceBytes, 7, (void *)&TechPrice);
    HookVtableSlot(GameStateVtable + 6, (void *)&GameStateLoad, (unsigned *)&OriginalGameStateLoad);
    HookVtableSlot(GameStateVtable + 7, (void *)&GameStateSave, (unsigned *)&OriginalGameStateSave);
    RetargetCallsTo(0x424110, (void *)&GameStateInitWrapper);
}
