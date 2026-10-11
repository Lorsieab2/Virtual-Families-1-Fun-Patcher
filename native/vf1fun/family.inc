// family.inc -- marriage, babies, adoption, divorce and eviction.
// Included by vf1fun.cpp after pages.inc. The rows mirror the Virtual
// Families 2 patcher's "Marriage and family" and "Pregnancy one-shots"
// Special Upgrades, plus Adopt a Child, Spawn a Baby, Adopt New Person and
// Evict Family. Every address and recipe is from research/villagers.md (read
// in VF1's own code); every hook is a call-site retarget or a vtable slot,
// installed only after the original bytes are checked.

// ---------------------------------------------------------------- game functions
typedef void *(__thiscall *ThisPtrFn)(void *self);
typedef bool (__thiscall *ThisBoolFn)(void *self);
typedef int (__thiscall *ThisIntFn)(void *self);
typedef bool (__thiscall *VillagerArgFn)(void *self, void *villager);
typedef bool (__thiscall *TwoVillagersFn)(void *self, void *a, void *b);
typedef bool (__thiscall *NextGenerationFn)(void *self, void *villager, int childIndex);
typedef void (__thiscall *LifeEventFn)(void *state, int id, int a, int b);
typedef void (__thiscall *IntArgFn)(void *self, int value);
typedef void (__thiscall *ForgetPlansFn)(void *villager, void *self);
typedef void (__thiscall *MoneySetFn)(void *money, float amount);
typedef bool (__thiscall *ChanceFn)(void *state, int a, int b, int c);
typedef bool (__thiscall *ImpregnateFn)(void *villager, int one, const char *father, int head, int body, int flag);
typedef int (__thiscall *Spawn3Fn)(void *manager, int voice, int gender, int age);
typedef int (__thiscall *Spawn12Fn)(void *manager, int voice, int gender, int age, const char *parent1,
                                    const char *parent2, int fatherBody, int fatherHead, int motherBody,
                                    int motherHead, int x, int y, int unused);
typedef void (__thiscall *SetActiveFn)(void *scene, bool active);
typedef void *(__cdecl *SceneRefFn)();

static void *const FamilyTree = (void *)0x5AB908;
static const ThisPtrFn GetCurrentFamily = (ThisPtrFn)0x481730;
static const ThisBoolFn CanMarry = (ThisBoolFn)0x481750;
static const ThisIntFn EmptyOffspringSlots = (ThisIntFn)0x4816E0;
static const VillagerArgFn AddOffspring = (VillagerArgFn)0x481AA0;
static const TwoVillagersFn UpdateParents = (TwoVillagersFn)0x4819C0;
static const NextGenerationFn StartNextGeneration = (NextGenerationFn)0x481B30;
static const VillagerArgFn StartFamilyTree = (VillagerArgFn)0x481E00;  // = Reset + StartNextGeneration(v, -1)
static const VoidThisFn MakeRoomInTree = (VoidThisFn)0x4818A0;
static const VoidThisFn ResetFamilyTree = (VoidThisFn)0x481560;
static const VoidThisFn ResetVillagers = (VoidThisFn)0x489800;           // CVillagerManager: all 30 slots
static const ThisPtrFn GetMatriarch = (ThisPtrFn)0x489950;
static const ThisPtrFn GetPatriarch = (ThisPtrFn)0x4899C0;
static const ThisIntFn Population = (ThisIntFn)0x48AC90;
static const VoidThisFn ClearFocus = (VoidThisFn)0x48A410;               // CVillagerManager
static const VoidThisFn DetachAll = (VoidThisFn)0x486860;                // CVillager
static const ForgetPlansFn ForgetPlans = (ForgetPlansFn)0x48C5A0;        // (v, v), as the death path
static const LifeEventFn QueueLifeEventPending = (LifeEventFn)0x423E10;
static const IntArgFn QueueMail = (IntArgFn)0x424500;                    // theGameState; 2 = marriage proposal
static const IntArgFn AddHappiness = (IntArgFn)0x48F9F0;                 // CVillagerState (Marry: 300)
static const IntArgFn AddHappinessTrend = (IntArgFn)0x48F990;            // CVillagerState (Marry: 10)
typedef void (__thiscall *ProgressFn)(void *self, int id, int amount);
static const ProgressFn IncrementProgress = (ProgressFn)0x413210;
static const MoneySetFn MoneySet = (MoneySetFn)0x422640;
static const ChanceFn ChanceOfPregnancy = (ChanceFn)0x48FC10;
static const ImpregnateFn Impregnate = (ImpregnateFn)0x4864D0;
static const Spawn3Fn SpawnPeep = (Spawn3Fn)0x48BC60;
static const Spawn12Fn SpawnPeepFull = (Spawn12Fn)0x48B2E0;
static const SetActiveFn SetSceneActive = (SetActiveFn)0x40C700;
static const SceneRefFn AdoptionScene = (SceneRefFn)0x436510;            // CAdoptionScene::Ref
static const VoidThisFn GeneratePeepCandidate = (VoidThisFn)0x4383D0;    // CDatingScene: the reroll
static unsigned *const DatingVtable = (unsigned *)0x4B6C64;

static unsigned char *GameStateBytes() { return (unsigned char *)GameStateGet(); }

// ---------------------------------------------------------------- family records
// CFamilyTree record: +0 used, +4 parent-1 SPeepRecord, +0xDC parent-2, +0x1B4
// child count. SPeepRecord: +0 name, +0x1A used, +0x28 villager slot (-1 gone).
static unsigned char *CurrentFamily() {
    unsigned char *r = (unsigned char *)GetCurrentFamily(FamilyTree);
    return r && r[0] ? r : 0;
}
static int RecordSlot(unsigned char *peep) {
    if (!peep[0x1A]) return -1;
    int slot = *(int *)(peep + 0x28);
    return slot >= 0 && slot < VillagerSlots && VillagerPresent(slot) ? slot : -1;
}
static int FounderSlot() { unsigned char *r = CurrentFamily(); return r ? RecordSlot(r + 4) : -1; }
static int SpouseSlot() { unsigned char *r = CurrentFamily(); return r ? RecordSlot(r + 0xDC) : -1; }
static bool GameOver() { return Population(VillagerManager) == 0 && *(int *)0x50C560 != 0; }
static bool Pregnant(int slot) { return slot >= 0 && *(int *)(Villager(slot) + 0x2AF8) != 0; }
static const char *VillagerName(int slot) { return (const char *)(Villager(slot) + 0x2A44); }

// ---------------------------------------------------------------- Change Appearance and the Family Tree
// The tree keeps its own copy of each person's head and body (SPeepRecord +0x20 /
// +0x24), written when the person joins (AddOffspring, StartNextGeneration);
// UpdatePeepRecord (0x4818F0) refreshes only the career and likes, so a changed
// look would never reach the tree portrait. This writes it into the CURRENT
// family's record for that villager (same slot and name); earlier generations'
// records are history and stay as they were.
static void SyncTreeLook(int slot) {
    unsigned char *r = CurrentFamily();
    if (!r) return;
    unsigned char *peeps[8];
    int n = 0;
    peeps[n++] = r + 4;
    peeps[n++] = r + 0xDC;
    int children = *(int *)(r + 0x1B4);
    for (int c = 0; c < children && c < 6; ++c) peeps[n++] = r + 0x1B8 + c * 0xD8;
    for (int i = 0; i < n; ++i) {
        unsigned char *p = peeps[i];
        if (p[0x1A] && *(int *)(p + 0x28) == slot && strncmp((const char *)p, VillagerName(slot), 25) == 0) {
            *(int *)(p + 0x20) = *(int *)(Villager(slot) + 0x2A60);
            *(int *)(p + 0x24) = *(int *)(Villager(slot) + 0x2A64);
        }
    }
}

// ---------------------------------------------------------------- pregnancy one-shots
// gVillage.armed: the next successful pregnancy (VF1 creates the babies at
// conception, CVillager::Impregnate 0x4864D0). Cleared when Impregnate succeeds.
enum { ARM_FORCE = 1, ARM_MALE = 2, ARM_FEMALE = 4, ARM_SINGLE = 8, ARM_TWINS = 16, ARM_TRIPLETS = 32 };

// 0x48EB8C: the try-for-a-baby step's ChanceOfPregnancy roll on the mother.
static bool gOlderPregnancies;
static bool gPrivateRomantic;
static bool __fastcall ChanceWrapper(void *state, void *, int a, int b, int c) {
    if (gVillage.armed & ARM_FORCE) return true;
    // Allow Older Pregnancies (the Virtual Families 2 patcher's curve): the stock roll is
    // certain failure for a mother over 50 (0x48FC97 `xor edi, edi`); here 10% at 50 tapers
    // to a 0.1% floor from 69 on, rolled in tenths of a percent. Mothers up to 50 are stock.
    int years = a / 20;
    if (gOlderPregnancies && years > 50) {
        int tenths = 100 - (years - 50) * 99 / 19;
        if (tenths < 1) tenths = 1;
        return GetRandom(1000) < tenths;
    }
    return ChanceOfPregnancy(state, a, b, c);
}
// 0x48EBB2: the same step's Impregnate call.
static bool __fastcall ImpregnateWrapper(void *v, void *, int one, const char *father, int head, int body, int flag) {
    bool ok = Impregnate(v, one, father, head, body, flag);
    if (ok) gVillage.armed = 0;
    return ok;
}
// 0x486570 / 0x486586: Impregnate's twin and triplet rolls, rand(100) against
// 7+bonus and 25+bonus. The game still checks the free child slots, so twins
// and triplets fall back to what the family has room for.
static int __cdecl FirstBabyRoll(int n) {
    if (gVillage.armed & ARM_SINGLE) return n - 1;
    if (gVillage.armed & (ARM_TWINS | ARM_TRIPLETS)) return 0;
    return GetRandom(n);
}
static int __cdecl SecondBabyRoll(int n) {
    if (gVillage.armed & ARM_TWINS) return n - 1;
    if (gVillage.armed & ARM_TRIPLETS) return 0;
    return GetRandom(n);
}
// 0x486627: Impregnate's spawn of the first baby; twins copy its gender.
static int __fastcall BabySpawnWrapper(void *m, void *, int voice, int gender, int age, const char *p1, const char *p2,
                                       int fb, int fh, int mb, int mh, int x, int y, int unused) {
    if (gVillage.armed & ARM_MALE) gender = 0;
    if (gVillage.armed & ARM_FEMALE) gender = 1;
    return SpawnPeepFull(m, voice, gender, age, p1, p2, fb, fh, mb, mh, x, y, unused);
}

// ---------------------------------------------------------------- marriage
// 0x43845F: CDatingScene::GeneratePeepCandidate spawns the candidate with the
// opposite gender of the family's adult (`sete dl` at 0x43844D). With
// Same-Sex Marriage on, every candidate gets the SAME gender instead (owner's
// choice: the setting shows same-sex candidates only).
static int __fastcall CandidateSpawnWrapper(void *m, void *, int voice, int gender, int age) {
    if (gVillage.sameSex) gender = gender ? 0 : 1;
    return SpawnPeep(m, voice, gender, age);
}

// The Marry button (0x43823F) does the wedding bookkeeping only when the game
// has both a matriarch and a patriarch, so for two women or two men it is
// skipped. This does the same steps for them, in the same order: baby
// cooldown flag, dowry achievements, same-career achievement, the dowry,
// CFamilyTree::UpdateParents, happiness, and the wedding life event.
static int ResidentAdult(int candidate) {
    int s = FounderSlot();
    if (s >= 0 && s != candidate) return s;
    for (int i = 0; i < VillagerSlots; ++i) {
        unsigned char *v = Villager(i);
        if (i != candidate && VillagerPresent(i) && !v[0x13578] && *(int *)(v + 0x2B6C) != -1)
            return i;
    }
    return -1;
}
static void SameGenderWedding(int resident, int candidate, int dowry) {
    unsigned char *a = Villager(resident), *b = Villager(candidate);
    *(int *)(GameStateBytes() + 0x1B150) = 1;
    if (dowry > 200) IncrementProgress(Achievements, 6, 1);
    else if (dowry < 75) IncrementProgress(Achievements, 7, 1);
    if (*(int *)(a + 0x2B6C) == *(int *)(b + 0x2B6C)) IncrementProgress(Achievements, 8, 1);
    MoneyAdjust(Money, (float)dowry, false);
    UpdateParents(FamilyTree, a, b);
    AddHappiness(a + 0x2AD4, 300); AddHappiness(b + 0x2AD4, 300);
    AddHappinessTrend(a + 0x2AD4, 10); AddHappinessTrend(b + 0x2AD4, 10);
    QueueLifeEventPending(GameStateGet(), 1, resident, candidate);
}

static HandleMessageFn OriginalDatingHandleMessage;
static bool __fastcall DatingHandleMessage(void *scene, void *, int message, int param) {
    unsigned char *s = (unsigned char *)scene;
    int candidate = *(int *)(s + 0xC);
    if (message == MessageButtonClicked && param == 2 && gVillage.reroll && candidate != -1) {
        GeneratePeepCandidate(scene);  // discards the old candidate itself
        return true;
    }
    if (message == MessageButtonClicked && param == 1 && candidate != -1) {
        bool native = GetMatriarch(VillagerManager) && GetPatriarch(VillagerManager);
        int resident = ResidentAdult(candidate), dowry = *(int *)(s + 8);
        bool r = OriginalDatingHandleMessage(scene, message, param);
        if (!native && resident >= 0 &&
            *(int *)(Villager(resident) + 0x2A38) == *(int *)(Villager(candidate) + 0x2A38))
            SameGenderWedding(resident, candidate, dowry);
        return r;
    }
    return OriginalDatingHandleMessage(scene, message, param);
}

// Force Marriage Email: the same mail the main scene queues (0x44526A) when a
// proposal is due. Only when the family can marry (parent-2 free).
static const wchar_t *ForceMarriageEmail() {
    if (!CurrentFamily() || !CanMarry(FamilyTree))
        return L"Nobody in the family can get married right now.";
    if (!GetMatriarch(VillagerManager) && !GetPatriarch(VillagerManager))
        return L"There is no adult to propose to.";
    QueueMail(GameStateGet(), 2);
    return L"A marriage proposal has been queued.";
}

// Divorce Spouse: research/villagers.md section 3's recipe. The spouse is the
// one who married in (parent-2 of the current family).
static const wchar_t *DivorceSpouse() {
    unsigned char *r = CurrentFamily();
    int spouse = SpouseSlot();
    if (!r || spouse < 0) return L"Nobody in the house is married.";
    if (Pregnant(spouse) || Pregnant(FounderSlot()))
        return L"Not while the family is expecting a baby.";
    unsigned char *v = Villager(spouse);
    DetachAll(v);
    ForgetPlans(v, v);
    if (v[0x13575]) ClearFocus(VillagerManager);
    v[0x13574] = 0;
    unsigned char *peep = r + 0xDC;
    *(int *)(peep + 0x28) = -1;
    peep[0x1A] = 0;
    SaveCurrentGame(GameStateGet());
    return 0;
}

// ---------------------------------------------------------------- children
static void SetName(int slot, const wchar_t *name) {
    char s[26] = { 0 };
    if (!name || !name[0]) return;
    WideCharToMultiByte(CP_ACP, 0, name, -1, s, 25, 0, 0);
    s[24] = 0;
    strncpy_s((char *)(Villager(slot) + 0x2A44), 0x19, s, _TRUNCATE);
}

// A child of the current couple, any age 2-13: the parents' names, heads and
// bodies go into the new villager the way a birth records them, so the look is
// inherited, and AddOffspring puts it in the Family Tree. Not a birth: no
// "new baby" event and no births statistic.
static const wchar_t *SpawnChild(int gender, int years, const wchar_t *name) {
    if (!CurrentFamily()) return L"There is no family yet.";
    if (EmptyOffspringSlots(FamilyTree) <= 0) return L"This family already has six children.";
    if (years < 2 || years > 13) return L"Enter an age from 2 to 13.";
    int a = FounderSlot(), b = SpouseSlot();
    if (a < 0) a = b;
    if (b < 0) b = a;
    if (a < 0) return L"A child needs at least one parent in the house.";
    unsigned char *p1 = Villager(a), *p2 = Villager(b);
    int slot = SpawnPeepFull(VillagerManager, -1, gender, years * 20, VillagerName(a), VillagerName(b),
                             *(int *)(p1 + 0x2A64), *(int *)(p1 + 0x2A60), *(int *)(p2 + 0x2A64),
                             *(int *)(p2 + 0x2A60), 0, 0, 0);
    if (slot < 0) return L"The house is full.";
    SetName(slot, name);
    AddOffspring(FamilyTree, Villager(slot));
    return 0;
}

// ---------------------------------------------------------------- Evict Family and Adopt New Person
// Both open the game's own new-family adoption screen (CAdoptionScene with
// +0x10 = 0, scene 7), as Next Generation opens it (0x43926C..0x43927A). On
// Adopt that screen starts a new family tree (0x4368C5) and sets the starting
// money (0x4368D6); while one of these is pending, both calls are adjusted:
// the money is kept, and Adopt New Person adds the new adult as the next
// generation of the existing tree instead of wiping it.
enum { ADOPT_NONE, ADOPT_EVICT, ADOPT_NEW_PERSON };  // gAdoptionMode, features.inc

static bool __fastcall AdoptStartFamilyTree(void *tree, void *, void *villager) {
    if (gAdoptionMode == ADOPT_NEW_PERSON) {
        if (*(int *)tree >= 30) MakeRoomInTree(tree);
        return StartNextGeneration(tree, villager, -1);
    }
    return StartFamilyTree(tree, villager);
}
static void __fastcall AdoptMoneySet(void *money, void *, float amount) {
    if (gAdoptionMode != ADOPT_NONE) {
        gAdoptionMode = ADOPT_NONE;
        return;
    }
    MoneySet(money, amount);
}

static void OpenNewFamilyAdoption(void *storeScene, int mode) {
    unsigned char *gs = GameStateBytes();
    gAdoptionMode = mode;
    SetSceneActive(storeScene, false);
    ClearFocus(VillagerManager);
    if (mode == ADOPT_EVICT) {  // VF2's Evict: reset the family tree and the villagers, keep the rest
        ResetFamilyTree(FamilyTree);
        ResetVillagers(VillagerManager);
    }
    // Nobody is left to deliver babies reserved earlier (theGameState::Init's value).
    *(int *)(gs + 0x1B120) = -1; *(int *)(gs + 0x1B124) = -1; *(int *)(gs + 0x1B128) = -1;
    ((unsigned char *)AdoptionScene())[0x10] = 0;
    *(int *)(gs + 0x1B300) = 7;
}

// ---------------------------------------------------------------- installation
// A `call rel32` at `site` that must currently reach `target`.
static bool RetargetCall(unsigned site, unsigned target, void *replacement) {
    unsigned char *p = (unsigned char *)site;
    if (p[0] != 0xE8) return false;
    unsigned now = site + 5 + *(int *)(p + 1);
    if (now == (unsigned)replacement) return true;
    if (now != target) return false;
    int rel = (int)((unsigned)replacement - (site + 5));
    return WriteCode(site + 1, &rel, 4);
}

// Force Successful Pregnancy skips the refusal that has nothing to do with whether a pregnancy would
// succeed (VF2: "exactly the random refusals, nothing else"). In VF1's drop-on-spouse pairing the
// only such refusal is the baby cooldown: the pairing compares gameState+0x1B150 with the current
// seconds (call at 0x4412CA, `cmp [ecx+0x1B150], eax; jae too_soon`, string 0x3E3 "too soon"). While
// the shot is armed that call reports the largest possible time, so the cooldown always counts as over.
static unsigned __fastcall PairingSeconds(void *gameState, void *) {
    if (gVillage.armed & ARM_FORCE) return 0xFFFFFFFFu;
    return ((unsigned (__thiscall *)(void *))0x4036D0)(gameState);
}
// A couple that cannot conceive ("private adult romantic time", VF2): same-sex, or an opposite-sex couple
// whose family already has six children. Used by the caption, and below by the cooldown.
static bool PrivateCoupleNow() {
    int a = FounderSlot(), b = SpouseSlot();
    if (a < 0 || b < 0) return false;
    return *(int *)(Villager(a) + 0x2A38) == *(int *)(Villager(b) + 0x2A38) || EmptyOffspringSlots(FamilyTree) <= 0;
}

// VF2's cooldown rule (VF2StoreTryForBabyCooldownMaybe): the failed-attempt cooldown is not stored for a
// couple that cannot conceive (so they can try again at once instead of "It is too soon to try to make a
// baby again."), nor for an older couple (50+) while Allow Older Pregnancies is on. VF1 stores it in the
// plan step that rolls ChanceOfPregnancy: `mov [eax+0x1B150], edi` (edi = now + 0x4B0, the same 1,200 s
// VF2 uses) at 0x48EC70.
extern "C" int __cdecl ShouldStoreFailedAttemptCooldown() {
    if (gPrivateRomantic && PrivateCoupleNow()) return 0;
    if (gOlderPregnancies) {
        // the mother only, over 50: the same boundary as ChanceWrapper
        int a = FounderSlot(), b = SpouseSlot();
        if (a >= 0 && b >= 0) {
            int ga = *(int *)(Villager(a) + 0x2A38), gb = *(int *)(Villager(b) + 0x2A38);
            int mother = ga == gb ? -1 : (ga == 1 ? a : b);
            if (mother >= 0 && *(int *)(Villager(mother) + 0x2A34) / 20 > 50) return 0;
        }
    }
    return 1;
}
__declspec(naked) static void CooldownStoreDetour() {
    __asm {
        pushad
        call ShouldStoreFailedAttemptCooldown
        test eax, eax
        popad                       // does not change the flags
        jz skip
        mov dword ptr [eax + 0x1B150], edi
    skip:
        push 0x48EC76               // the stock code continues with `call 0x48F9F0`
        ret
    }
}
static void InstallCooldownRule() {
    static const unsigned char stock[] = { 0x89, 0xB8, 0x50, 0xB1, 0x01, 0x00 };  // mov [eax+0x1B150], edi
    InstallJump(0x48EC70, stock, 6, (void *)&CooldownStoreDetour);
}

static void InstallChanceHook() {  // Allow Older Pregnancies and Force Successful Pregnancy share this call site
    RetargetCall(0x48EB8C, 0x48FC10, (void *)&ChanceWrapper);
    RetargetCall(0x4412CA, 0x4036D0, (void *)&PairingSeconds);
}

// Next Generation. The Family Tree screen shows its Next Generation button only when the
// current family's "a parent died and children survive" flag is set (CFamilyTree
// 0x481780, called at 0x439390). With the Older Villager Mortality Curve there is no
// hard maximum age, so parents may never die: the button is also offered when the
// oldest parent still at home is 60 or older and a child survives (the Virtual
// Families 2 patcher's rule). The game's own flow then retires everyone but the
// chosen heir, as it does after a death.
static bool __fastcall NextGenerationGate(void *tree) {
    typedef bool (__thiscall *FlagFn)(void *);
    if (((FlagFn)0x481780)(tree)) return true;
    if (!gMortalityOn || !CurrentFamily()) return false;
    if (((ThisIntFn)0x481850)(tree) <= 0) return false;  // CountSurvivingChildren
    int a = FounderSlot(), b = SpouseSlot();
    int oldest = 0;
    if (a >= 0) oldest = *(int *)(Villager(a) + 0x2A34);
    if (b >= 0 && *(int *)(Villager(b) + 0x2A34) > oldest) oldest = *(int *)(Villager(b) + 0x2A34);
    return oldest >= 60 * 20;
}
static void InstallNextGenerationGate() {
    RetargetCall(0x439390, 0x481780, (void *)&NextGenerationGate);
}

static void InstallFamilyHooks() {
    RetargetCall(0x4368C5, 0x481E00, (void *)&AdoptStartFamilyTree);
    RetargetCall(0x4368D6, 0x422640, (void *)&AdoptMoneySet);
    RetargetCall(0x48EBB2, 0x4864D0, (void *)&ImpregnateWrapper);
    RetargetCall(0x486570, 0x403650, (void *)&FirstBabyRoll);
    RetargetCall(0x486586, 0x403650, (void *)&SecondBabyRoll);
    RetargetCall(0x486627, 0x48B2E0, (void *)&BabySpawnWrapper);
    RetargetCall(0x43845F, 0x48BC60, (void *)&CandidateSpawnWrapper);
    HookVtableSlot(DatingVtable + 3, (void *)&DatingHandleMessage, (unsigned *)&OriginalDatingHandleMessage);
}
