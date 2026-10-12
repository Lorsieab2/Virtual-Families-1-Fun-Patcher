// computer.inc -- the computer's two activities, browsing the web (behavior 0x6D) and playing video games
// (behavior 0x10E), are chosen 50:50, as in the Virtual Families 2 patcher. VF2 does this under its
// "Behavior Patches" setting, the same setting that holds its behavior labels, so here it belongs to
// "Behavior Label Variants". VF2 does it in two places, and so does this file:
//
// 1. A villager dropped on a computer. VF1's computer hotspot handler (0x495470, reached from
//    theMainScene::HandleDropOnHotSpot 0x441020 through the hotspot table at 0x8754C8, types 0x12 and
//    0x1E) first takes its power-failure (0x121), unread-mail (0x6E, "Reading email") and career-work
//    (0x33, or 0x133 with "not up for it") routes, and only otherwise starts ordinary browsing with
//    `push 0x6D; call CVillager::NewBehavior`
//    at 0x495558. VF2 replaces exactly that ordinary result: after the drop, a villager now browsing the
//    web plays a video game instead when ldwGameState::GetRandom(2) != 0. Here the one call that starts
//    ordinary browsing makes that same roll and starts the video game instead, so the behavior starts once
//    and every other computer route is untouched.
//
// 2. A villager choosing for itself. CVillager::InitAI (0x482120) fills the candidate table at villager
//    +0x2B98 + id*0xC8 (+0x0C the weight, +0xC4 the enabled byte); the decision pass (0x4886E0) picks among
//    the eligible, enabled candidates by weight and starts the winner with NewBehavior. Stock VF1 gives
//    browsing 3300 and video games 1500 (each +/- 20%), so browsing won about two times in three. VF2 sets
//    both candidates to 650 after InitAI and after LoadAI (whose saved weights otherwise come back);
//    so does this. Both candidates are already enabled in stock VF1 and their own age and object rules
//    stay as they are, as does the decision pass's own email route (0x6F, tried before the weighted
//    choice). As in VF2, a liked or disliked activity still has its weight raised or lowered by
//    the decision pass, and praise or scolding still trains the weight during a session (VF2's own
//    known limitation: the weight returns to 650 on the next load).
//
// The weights are ordinary candidate weights inside the save's normal range; nothing new is stored.

static const int kComputerWebBehavior = 0x6D;   // BrowsingWeb: Behavior table entry 0x47EB30
static const int kComputerGameBehavior = 0x10E; // PlayingVideoGame: Behavior table entry 0x476A30
static const int kComputerCandidateWeight = 650; // VF2: EnableAllAgesAutonomousCandidateWithWeight(.., 650)

typedef void (__thiscall *NewBehaviorFn)(unsigned char *villager, int behavior, void *data);
static const NewBehaviorFn NewBehavior = (NewBehaviorFn)0x4858D0;  // CVillager::NewBehavior, ret 8

// The ordinary browsing route of the computer hotspot (call at 0x495558).
static void __fastcall ComputerDropBehavior(unsigned char *villager, void *, int behavior, void *data) {
    if (behavior == kComputerWebBehavior && GetRandom(2) != 0)
        behavior = kComputerGameBehavior;
    NewBehavior(villager, behavior, data);
}

static void SetComputerCandidateWeights(unsigned char *villager) {
    *(int *)(villager + 0x2B98 + kComputerGameBehavior * 0xC8 + 0x0C) = kComputerCandidateWeight;
    *(int *)(villager + 0x2B98 + kComputerWebBehavior * 0xC8 + 0x0C) = kComputerCandidateWeight;
}

// CVillager::InitAI (0x482120, thiscall, no arguments).
static void __fastcall ComputerInitAI(unsigned char *villager, void *) {
    ((void (__thiscall *)(unsigned char *))0x482120)(villager);
    SetComputerCandidateWeights(villager);
}

// CVillager::LoadAI (0x4855D0, thiscall, SSaveState&): InitAI, then the saved weights.
static void __fastcall ComputerLoadAI(unsigned char *villager, void *, void *state) {
    ((void (__thiscall *)(unsigned char *, void *))0x4855D0)(villager, state);
    SetComputerCandidateWeights(villager);
}

static void InstallComputerFiftyFifty() {
    RetargetCall(0x495558, 0x4858D0, (void *)&ComputerDropBehavior);  // computer hotspot: ordinary browsing
    RetargetCall(0x484EED, 0x482120, (void *)&ComputerInitAI);        // CVillager::Init
    RetargetCall(0x48531C, 0x482120, (void *)&ComputerInitAI);        // villager init 0x485310 (SpawnSpecificPeep)
    RetargetCall(0x48547C, 0x482120, (void *)&ComputerInitAI);        // CVillager::CloneAsAdult
    RetargetCall(0x4857D6, 0x4855D0, (void *)&ComputerLoadAI);        // CVillager::LoadState
}
