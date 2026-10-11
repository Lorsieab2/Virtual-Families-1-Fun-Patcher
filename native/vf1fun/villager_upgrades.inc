// villager_upgrades.inc -- the Virtual Families 2 patcher's villager-details
// upgrades that exist in Virtual Families 1, as free rows on the Villager
// Cheats page (VF2 sells them for coins; every Cheat Upgrade is free):
//   Boarding School            a child leaves the house like the game's own
//                              "is going to college" departure
//   Systematic Desensitization removes one dislike
//   Higher Learning Classes    adds a like the villager neither has nor dislikes
//   Psychotherapy              overcomes depression (fills happiness)
//   Add Running Like           gives the liking for running, clears the dislike
//   Set Age to 18              this villager only
// "Advanced Career Training" (promotion) and "Career Change" are in vf1fun.cpp.
//
// Likes and dislikes are two 3-slot lists of indexes (-1 = empty) at villager
// +0x13620 and +0x1362C, into the comma-separated name lists of strings 0x45B
// (likes, read by 0x481E20) and 0x45C (dislikes, read by 0x481420).

static const char *LikeNames() { return GetString(StringsGet(), 0x45B); }
static const char *DislikeNames() { return GetString(StringsGet(), 0x45C); }

static int NameIndex(const char *list, const char *name) {  // index of `name` in "a, b, c", or -1
    if (!list) return -1;
    size_t n = strlen(name);
    int index = 0;
    const char *p = list;
    while (*p) {
        while (*p == ' ') ++p;
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        if (len == n && strncmp(p, name, n) == 0) return index;
        if (!end) break;
        p = end + 1;
        ++index;
    }
    return -1;
}
static int NameCount(const char *list) {
    if (!list || !*list) return 0;
    int n = 1;
    for (const char *p = list; *p; ++p) if (*p == ',') ++n;
    return n;
}
static bool NameAt(const char *list, int index, char *out, int cap) {
    const char *p = list;
    for (int i = 0; p && *p; ++i) {
        while (*p == ' ') ++p;
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        if (i == index) {
            if ((int)len >= cap) len = cap - 1;
            memcpy(out, p, len); out[len] = 0;
            return true;
        }
        if (!end) break;
        p = end + 1;
    }
    return false;
}

static int *Likes(int i) { return (int *)(Villager(i) + 0x13620); }
static int *Dislikes(int i) { return (int *)(Villager(i) + 0x1362C); }

// Gives the like called `name`, and clears the matching dislike. Returns 0 when done, or the reason.
static const wchar_t *GiveLike(int i, const char *name) {
    int like = NameIndex(LikeNames(), name);
    if (like < 0) return L"The game has no such like.";
    int *l = Likes(i);
    bool has = false;
    for (int s = 0; s < 3; ++s) if (l[s] == like) has = true;
    if (!has) {
        int slot = -1;
        for (int s = 0; s < 3 && slot < 0; ++s) if (l[s] == -1) slot = s;
        if (slot < 0) return L"Every like slot is already full.";
        l[slot] = like;
    }
    int dislike = NameIndex(DislikeNames(), name);
    int *d = Dislikes(i);
    for (int s = 0; s < 3; ++s) if (dislike >= 0 && d[s] == dislike) d[s] = -1;
    return 0;
}

static const wchar_t *RemoveOneDislike(int i) {
    int *d = Dislikes(i);
    for (int s = 0; s < 3; ++s)
        if (d[s] != -1) { d[s] = -1; return 0; }
    return L"Has no dislikes.";
}

static const wchar_t *LearnNewLike(int i) {
    const char *likes = LikeNames(), *dislikes = DislikeNames();
    int total = NameCount(likes);
    if (total <= 0) return L"The game has no likes list.";
    for (int tries = 0; tries < 400; ++tries) {
        char name[48];
        if (!NameAt(likes, GetRandom(total), name, sizeof name)) continue;
        int like = NameIndex(likes, name), dislike = NameIndex(dislikes, name);
        int *l = Likes(i), *d = Dislikes(i);
        bool taken = false;
        for (int s = 0; s < 3; ++s) {
            if (l[s] == like) taken = true;
            if (dislike >= 0 && d[s] == dislike) taken = true;
        }
        if (!taken) return GiveLike(i, name);
    }
    return L"Nothing new to learn.";
}

static const wchar_t *Psychotherapy(int i) {
    *Stat(i, STAT_HAPPINESS) = 100;
    return 0;
}

// Age in units is villager +0x2A34, 20 units = 1 year. The result is VF2SetSelectedVillagerAge's: the age
// becomes 360 (18 years). An older villager is written directly, as VF2 does. A younger one goes through
// VF1's own IncrementAge (0x4897F0), like the Time Warp, so each skipped year's processing still runs in
// order (VF1 does that processing inside IncrementAge, so a direct write would skip it).
typedef void (__thiscall *IncrementAgeFn)(void *age, int amount);
static const wchar_t *SetAgeTo18(int i) {
    int *age = (int *)(Villager(i) + 0x2A34);
    const int target = 18 * 20;
    if (*age < target) ((IncrementAgeFn)0x4897F0)(age, target - *age);
    else *age = target;
    return 0;
}

// The game's own "goes to college" departure (0x489EB5..0x489ED8): forget plans,
// SetLeftHome, life event 5 (the "is going to college!" picture). Children only.
typedef void (__thiscall *SetLeftHomeFn)(void *villager);
static const wchar_t *BoardingSchool(int i) {
    if (HasCareer(i)) return L"Boarding school is for children only.";
    unsigned char *v = Villager(i);
    if (v[0x13578]) return L"Has already left home.";
    ForgetPlans(v, v);
    if (v[0x13575]) ClearFocus(VillagerManager);
    ((SetLeftHomeFn)0x4857F0)(v);
    QueueLifeEventPending(GameStateGet(), 5, *(int *)(v + 0x13538), -1);
    return 0;
}

static const wchar_t *ApplyVillagerUpgrade(int id, int slot) {
    switch (id) {
    case ID_VC_BOARD: return BoardingSchool(slot);
    case ID_VC_DESENS: return RemoveOneDislike(slot);
    case ID_VC_LEARN: return LearnNewLike(slot);
    case ID_VC_PSYCHO: return Psychotherapy(slot);
    case ID_VC_RUNNING: return GiveLike(slot, "running");
    case ID_VC_AGE18: return SetAgeTo18(slot);
    }
    return 0;
}
