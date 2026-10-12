// computer.inc -- the computer's two activities, browsing the web (behavior 0x6D) and playing video games
// (behavior 0x10E), are chosen 50:50, as in the Virtual Families 2 patcher. VF2 does this under its
// "Behavior Patches" setting, the same setting that holds its behavior labels, so here it belongs to
// "Behavior Label Variants". It covers both ways a villager starts using the computer:
//
// 1. A villager dropped on a computer. VF1's computer hotspot handler (0x495470, reached from
//    theMainScene::HandleDropOnHotSpot 0x441020 through the hotspot table at 0x8754C8, types 0x12 and
//    0x1E) first takes its power-failure (0x121), unread-mail (0x6E, "Reading email") and career-work
//    (0x33, or 0x133 with "not up for it") routes, and only otherwise starts ordinary browsing with
//    `push 0x6D; call CVillager::NewBehavior` at 0x495558. VF2 replaces exactly that ordinary result:
//    after the drop, a villager now browsing the web plays a video game instead when
//    ldwGameState::GetRandom(2) != 0. Here the one call that starts ordinary browsing makes that same
//    roll and starts the video game instead, so the behavior starts once and every other computer route
//    is untouched.
//
// 2. A villager choosing for itself. CVillager::InitAI (0x482120) fills the candidate table at villager
//    +0x2B98 + id*0xC8 (+0x0C the weight, +0xC4 the enabled byte); stock VF1 gives browsing 3300 and
//    video games 1500 (each +/- 20%), so browsing wins about two times in three. The decision pass
//    (0x4886E0) first lists the candidates that are enabled and pass their gates this time, then reads
//    each listed candidate's weight (`mov ebx, [ecx+ebp+0x2BA4]` at 0x488CA9), then may triple it (the
//    entry's need/interest conditions) or quarter it (a disliked interest), and rolls over the sum. When
//    both computer activities are in that list, the read is changed so that the two share their combined
//    weight evenly: browsing gets (w6D + w10E) / 2 and video games the rest, so their total and every
//    other candidate's chance are as in stock VF1. The multipliers still apply afterwards, as in VF2.
//    When only one of them is listed (for example a villager too young to browse), it keeps its own
//    weight. The owner's choice: VF2 instead writes 650 into both weights, but here nothing is written;
//    the weights in the villager (and in the save) stay the game's own, praise and scolding still train
//    them, and turning the setting off is exactly stock VF1.

static const int kComputerWebBehavior = 0x6D;   // BrowsingWeb: Behavior table entry 0x47EB30
static const int kComputerGameBehavior = 0x10E; // PlayingVideoGame: Behavior table entry 0x476A30

typedef void (__thiscall *NewBehaviorFn)(unsigned char *villager, int behavior, void *data);
static const NewBehaviorFn NewBehavior = (NewBehaviorFn)0x4858D0;  // CVillager::NewBehavior, ret 8

// The ordinary browsing route of the computer hotspot (call at 0x495558).
static void __fastcall ComputerDropBehavior(unsigned char *villager, void *, int behavior, void *data) {
    if (behavior == kComputerWebBehavior && GetRandom(2) != 0)
        behavior = kComputerGameBehavior;
    NewBehavior(villager, behavior, data);
}

static int ComputerStoredWeight(const unsigned char *villager, int id) {
    return *(const int *)(villager + 0x2B98 + id * 0xC8 + 0x0C);
}

// The base weight the decision pass uses for candidate `id`; `listed` holds the `count` candidate ids
// that passed this pass's gates. Reads only.
extern "C" int __cdecl VF1ComputerCandidateWeight(const unsigned char *villager, int id, int weight,
                                                   const int *listed, unsigned count) {
    if (id != kComputerWebBehavior && id != kComputerGameBehavior) return weight;
    int other = id == kComputerWebBehavior ? kComputerGameBehavior : kComputerWebBehavior;
    bool both = false;
    for (unsigned i = 0; i < count; ++i)
        if (listed[i] == other) { both = true; break; }
    if (!both) return weight;
    int sum = ComputerStoredWeight(villager, kComputerWebBehavior) + ComputerStoredWeight(villager, kComputerGameBehavior);
    int half = sum / 2;
    return id == kComputerWebBehavior ? half : sum - half;  // the two always add up to the stock total
}

// Entered by a jmp at 0x488CA9, replacing `mov ebx, [ecx+ebp+0x2BA4]; lea esi, [ecx+ebp]` (10 bytes) in
// the decision pass's weighting loop. There: ebp = the villager, edi = the candidate id (from the list at
// [esp+0x20], [esp+0x14] the index), ecx = id*0xC8, and the flags hold `test eax, eax` (0x488CA7) for the
// `je` at 0x488CB3, where it returns. The loop has no pushes, so [esp+0x1C] is the listed count and
// [esp+0x20] the list throughout.
static const unsigned char kComputerWeightBytes[] = { 0x8B, 0x9C, 0x29, 0xA4, 0x2B, 0x00, 0x00, 0x8D, 0x34, 0x29 };
__declspec(naked) static void ComputerWeightDetour() {
    __asm {
        mov ebx, dword ptr [ecx + ebp + 0x2BA4]
        lea esi, [ecx + ebp]
        pushfd
        push eax
        push ecx
        push edx
        mov eax, dword ptr [esp + 0x10 + 0x1C]   // listed count
        lea edx, [esp + 0x10 + 0x20]             // listed ids
        push eax
        push edx
        push ebx
        push edi
        push ebp
        call VF1ComputerCandidateWeight
        add esp, 20
        mov ebx, eax
        pop edx
        pop ecx
        pop eax
        popfd
        push 0x488CB3
        ret
    }
}

static void InstallComputerFiftyFifty() {
    RetargetCall(0x495558, 0x4858D0, (void *)&ComputerDropBehavior);  // computer hotspot: ordinary browsing
    InstallJump(0x488CA9, kComputerWeightBytes, sizeof kComputerWeightBytes, (void *)&ComputerWeightDetour);
}
