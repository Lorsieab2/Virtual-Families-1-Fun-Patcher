// vf1revive.dll -- "Revive a Family Member", the Virtual Families 1 Fun Patcher's companion for one feature.
// One feature, one DLL. The Virtual Villagers patcher's "Revive Buried/Disappeared Villagers" ported to VF1
// (docs/REVIVE.md).
//
// What it does (the owner's decisions, 2026-11-26): a family member who DIED (never one who divorced, left with the
// Talent Scout or was evicted) can be brought back, in the game, from vf1fun's Family page, for money (free while Free
// and Guaranteed Cheats is on; the price is vf1fun's kRevivePrice). They come back as the same person: the name (the
// whole name of the Names file too), sex, head and body, the parents' names and looks, likes and dislikes, career,
// fertility and "Wants kids?". Their moods and needs start fresh (the game's own new villager). Someone who died at
// 20 or older comes back at exactly the game's 20-year mark (400 age units); someone who died younger comes back at the
// age they died at, in the game's own units. Only the current generation, for now.
//
// How: a snapshot is taken at every death, from the game's memory, BEFORE the Family Tree forgets the person (the two
// calls of CFamilyTree::ReportDeath, the same sites vf1logs.dll hooks, chained). The snapshots live in a sidecar beside
// each save FILE, never in the save:
//
//   <save folder>\Virtual Families 1 Patcher Data\Revive\<save file>.dat
//
// in the Up to 28 Children sidecar's layout (vf1kids.cpp): written right after theGameState::Save(slot), rotated with
// the save (N -> N+20 -> N+40), naming the FNV-1a 64 hash and size of the save it was written with, so it always
// matches the save beside it. A file that does not validate is set aside (".unreadable-<k>.dat"), never overwritten or
// deleted; a file another program holds open is left exactly as it is. patcher/vf1_revive_backfill.py writes the same
// format for people who died before the patch (every field marked exact, inferred or unknown).
//
// Reviving: the game's own creator (SpawnPeepFull, as vf1fun's Spawn Child) makes the new villager at the revival age,
// then the snapshot's persistent fields are written over it and read back (all or none: on any difference the new
// villager is taken away again). The Family Tree: a child of the current generation gets their own entry back (its
// villager slot); a parent gets their entry back, or the empty spouse place when it is still empty and their partner
// is still the other parent; a spouse whose partner has remarried returns as a family member, not a spouse, in a child
// entry of the generation (as the Virtual Families 2 patcher). A revived parent or spouse with no career stays at home
// as a grown-up: the ageing pass's at-19 college exit is not taken for them (HasCareerAt19 below).
//
// vf1fun.dll loads this DLL (while the Revive setting is on) after vf1kids.dll and vf1logs.dll and calls
// VF1Revive_Startup() once. Installing is: setting -> verify every pin (vf1revive_sites.h, proved by
// tools/vf1_revive_sites.py) -> plan -> apply, all or nothing. VF1 has no ASLR.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "vf1revive_sites.h"

struct ReviveStatus {
    unsigned magic;
    unsigned version;
    unsigned requested;
    unsigned resolved;
    unsigned installed;
    unsigned entries;    // snapshots held now
    unsigned captured;   // snapshots taken this session
    unsigned lastLoad;   // 0 none, 1 exact sidecar, 2 backup sidecar, 3 another save of this family, 4 nothing,
                         // 5 moved aside, 6 shut (left as it is), 7 damaged but could not be moved aside
    unsigned lastSave;   // 0 none, 1 written, 2 nothing to write, 3 write failed, 4 a sidecar was shut or could not be
                         // moved aside: nothing was written or replaced
    unsigned revived;    // revivals this session
};
extern "C" __declspec(dllexport) volatile ReviveStatus VF1Revive_Status = { 0x56523156u, 1u, 0, 0, 0, 0, 0, 0, 0, 0 };

static HMODULE ThisModule;
static wchar_t Folder[MAX_PATH];

static void Copy(void *dst, const void *src, unsigned n) {
    volatile unsigned char *d = (volatile unsigned char *)dst;
    const volatile unsigned char *s = (const volatile unsigned char *)src;
    for (unsigned i = 0; i < n; ++i) d[i] = s[i];
}

static void Zero(void *dst, unsigned n) {
    volatile unsigned char *d = (volatile unsigned char *)dst;
    for (unsigned i = 0; i < n; ++i) d[i] = 0;
}

static bool Same(const void *a, const void *b, unsigned n) {
    const unsigned char *x = (const unsigned char *)a, *y = (const unsigned char *)b;
    for (unsigned i = 0; i < n; ++i) if (x[i] != y[i]) return false;
    return true;
}

static unsigned Length(const char *s) { unsigned n = 0; while (s && s[n]) ++n; return n; }

static bool NameEquals(const char *a, const char *b) {
    for (unsigned i = 0; i < REV_VILLAGER_NAME_LEN; ++i) {
        if (a[i] != b[i]) return false;
        if (!a[i]) return true;
    }
    return true;
}

// ---------------------------------------------------------------- log
static bool LogStarted;

#ifdef VF1REVIVE_TEST
static void Log(const char *, unsigned = 0, unsigned = 0) {}
#else
static void Log(const char *fmt, unsigned a = 0, unsigned b = 0) {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 14 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"vf1revive.log";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    char line[300];
    unsigned len = 0, which = 0;
    for (const char *f = fmt; *f && len + 14 < sizeof(line); ++f) {
        if (f[0] == '%' && f[1] == 'u') {
            unsigned v = which++ ? b : a;
            char d[12];
            unsigned k = 0;
            do { d[k++] = (char)('0' + v % 10); v /= 10; } while (v && k < 11);
            while (k) line[len++] = d[--k];
            ++f;
        } else {
            line[len++] = *f;
        }
    }
    line[len++] = '\r';
    line[len++] = '\n';
    HANDLE h = CreateFileW(path, LogStarted ? FILE_APPEND_DATA : GENERIC_WRITE, FILE_SHARE_READ, 0,
                           LogStarted ? OPEN_ALWAYS : CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    LogStarted = true;
    DWORD written = 0;
    WriteFile(h, line, len, &written, 0);
    CloseHandle(h);
}
#endif

// ================================================================ the game
typedef void (__thiscall *ReportDeathFn)(void *tree, void *villager);
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
typedef int (__thiscall *SpawnFullFn)(void *manager, int voice, int gender, int age, const char *parent1,
                                      const char *parent2, int fatherBody, int fatherHead, int motherBody,
                                      int motherHead, int x, int y, int unused);

static ReportDeathFn NextDeathEnd, NextBodyRemoval;
static GameStateSlotFn NextLoad, NextSave;

static unsigned char *Tree() { return (unsigned char *)REV_FAMILY_TREE; }
static unsigned char *Manager() { return (unsigned char *)REV_VILLAGER_MANAGER; }
static unsigned char *GameState() { return *(unsigned char **)REV_GAME_STATE_INSTANCE; }
static int I32(const unsigned char *p, unsigned off) { return *(const int *)(p + off); }
static void W32(unsigned char *p, unsigned off, int v) { *(int *)(p + off) = v; }

static unsigned char *Villager(int slot) {
    if (slot < 0 || slot >= (int)REV_HOUSEHOLD_SLOTS) return 0;
    return Manager() + REV_VILLAGER_ARRAY_OFFSET + (unsigned)slot * REV_VILLAGER_STRIDE;
}

static int SlotOf(const void *villager) {
    if (!villager) return -1;
    unsigned off = (unsigned)villager - (unsigned)(Manager() + REV_VILLAGER_ARRAY_OFFSET);
    if (off % REV_VILLAGER_STRIDE || off / REV_VILLAGER_STRIDE >= REV_HOUSEHOLD_SLOTS) return -1;
    return (int)(off / REV_VILLAGER_STRIDE);
}

static int Generations() {
    int g = I32(Tree(), 0);
    return g < 0 || g > (int)REV_TREE_GENERATIONS ? 0 : g;
}

static unsigned char *CurrentFamily() {
    int gen = Generations();
    if (gen <= 0) return 0;
    unsigned char *rec = Tree() + (unsigned)gen * REV_FAMILY_RECORD_SIZE - REV_FAMILY_RECORD_BASE;
    return rec[0] ? rec : 0;
}

static int StockChildren(const unsigned char *rec) {
    int n = I32(rec, REV_RECORD_CHILD_COUNT);
    return n < 0 ? 0 : n > (int)REV_TREE_CHILDREN ? (int)REV_TREE_CHILDREN : n;
}

static unsigned char *Peep(unsigned char *rec, int which) {    // 0 parent 1, 1 parent 2, 2.. children
    if (which == 0) return rec + REV_RECORD_PARENT1;
    if (which == 1) return rec + REV_RECORD_PARENT2;
    return rec + REV_RECORD_CHILDREN + (unsigned)(which - 2) * REV_PEEP_RECORD_SIZE;
}

// The companions this DLL asks, when they are loaded (each is optional).
static FARPROC Companion(const wchar_t *dll, const char *name) {
    HMODULE m = GetModuleHandleW(dll);
    return m ? GetProcAddress(m, name) : 0;
}

typedef const char *(__cdecl *FullNameFn)(const char *);
typedef int (__cdecl *StoreNameFn)(const char *full, int room, char *out);
static FARPROC TextFunction(const char *name) {
    FARPROC f = Companion(L"vf1text.dll", name);
    return f ? f : Companion(L"vf1font.dll", name);
}

typedef int (__cdecl *KidsExtraFn)(int slot, int gender, const char *name);
typedef int (__cdecl *KidsRevivedFn)(int oldSlot, int gender, const char *name, int newSlot);
typedef int (__cdecl *SkinToneOfFn)(int slot, int *birth);
typedef int (__cdecl *SkinToneGiveFn)(int slot, int tone, int birth);

// ================================================================ the snapshots
// One entry, exactly as the sidecar holds it (patcher/vf1_revive_backfill.py ENTRY_LAYOUT is the same table):
enum {
    E_STATE = 0,           // 1 dead, 2 revived
    E_SOURCE = 4,          // 1 captured at the death, 2 a stale record in the save, 3 an older save of the family,
                           // 4 a backup, 5 the Family Tree only, 6 the Family History log only
    E_MARKS = 8,           // u64: 2 bits per field (FIELD_*): 0 unknown, 1 inferred, 2 exact
    E_SLOT = 16,           // the villager slot at death
    E_ROLE = 20,           // -1 not in the Family Tree, 0 parent 1, 1 parent 2, 2..7 stock child, 8 child 7..28
    E_GENERATION = 24,
    E_DEATH_NUMBER = 28,   // the Family History log's "Death <n>", 0 when not known
    E_TIME = 32,           // u64 FILETIME of the capture, 0 for a backfill
    E_REVIVED_SLOT = 40,   // the slot they came back in, -1 while dead
    E_HOW = 44,            // how they came back (BACK_*), 0 while dead
    E_BIO = 48,            // CVillagerBio, 0xA0 bytes (age, sex, name index, voice, name, head, body, parents)
    E_VSTATE = 208,        // CVillagerState, 0x98 bytes (health, cause, fertility, "Wants kids?", the moods)
    E_SKILLS = 360,        // career, level, +8, salary
    E_LIKES = 376,         // likes int[3], dislikes int[3]
    E_PEEP = 400,          // their own Family Tree entry (SPeepRecord, 0xD8) at death; zeros when none
    E_PARENT1 = 616,       // the current generation's parent 1 entry at death (who the family was)
    E_PARENT2 = 832,       // ... and parent 2
    E_WHOLE = 1048,        // the whole name (the Names file's), stored form, NUL-terminated
    E_WHOLE_SIZE = 1204,
    E_SKIN = 2252,         // vf1skin.dll's two bytes at death: the tone (0 none, 1..10, 15 game's own) and the birth tone
    kEntry = 2256,
};
enum { STATE_DEAD = 1, STATE_REVIVED = 2 };
enum { SOURCE_CAPTURED = 1 };
enum { FIELD_NAME, FIELD_SEX, FIELD_HEAD, FIELD_BODY, FIELD_VOICE, FIELD_NAME_INDEX, FIELD_PARENTS, FIELD_LIKES,
       FIELD_DISLIKES, FIELD_CAREER, FIELD_FERTILITY, FIELD_WANTS_KIDS, FIELD_AGE, FIELD_CAUSE, FIELD_TREE,
       FIELD_WHOLE_NAME, FIELD_GENERATION, FIELD_COUNT };
// MARK_UNKNOWN_ADULT: the age at death only, when the backfill could not find it: "unknown -> 20".
enum { MARK_UNKNOWN = 0, MARK_INFERRED = 1, MARK_EXACT = 2, MARK_UNKNOWN_ADULT = 3 };
enum { BIO_AGE = 0, BIO_SEX = 4, BIO_NAME_INDEX = 8, BIO_VOICE = 0xC, BIO_NAME = 0x10, BIO_HEAD = 0x2C, BIO_BODY = 0x30,
       BIO_PARENTS = 0x34, BIO_PARENTS_SIZE = 0x44, ST_CAUSE = 0x10, ST_FERTILITY = 0x4C, ST_WANTS_KIDS = 0x50 };
static const unsigned kMaxEntries = 64;

static unsigned char Entries[kMaxEntries][kEntry];
static unsigned EntryCount;
static int GenerationsSeen;      // the tree's generations at the last load or save: a lower count is a new family

static unsigned Mark(const unsigned char *e, int field) {
    unsigned long long m = *(const unsigned long long *)(e + E_MARKS);
    return (unsigned)(m >> (2 * field)) & 3u;
}

static void ClearEntries() {
    EntryCount = 0;
    VF1Revive_Status.entries = 0;
}

// The same person, as the game tells people apart: name, sex, head and body.
static bool IsPerson(const unsigned char *e, const unsigned char *v) {
    return NameEquals((const char *)(v + REV_VILLAGER_NAME), (const char *)(e + E_BIO + BIO_NAME))
        && I32(v, REV_VILLAGER_GENDER) == I32(e, E_BIO + BIO_SEX)
        && I32(v, REV_VILLAGER_HEAD) == I32(e, E_BIO + BIO_HEAD)
        && I32(v, REV_VILLAGER_BODY) == I32(e, E_BIO + BIO_BODY);
}

static bool AliveNow(const unsigned char *e) {
    for (int s = 0; s < (int)REV_HOUSEHOLD_SLOTS; ++s) {
        const unsigned char *v = Villager(s);
        if (v[REV_VILLAGER_PRESENT] && I32(v, REV_VILLAGER_HEALTH) > 0 && IsPerson(e, v)) return true;
    }
    return false;
}

static bool PeepIs(const unsigned char *peep, const char *name, int sex) {
    return peep[REV_PEEP_VALID] && NameEquals((const char *)peep, name) && I32(peep, REV_PEEP_GENDER) == sex;
}

static unsigned char *NewEntry() {
    if (EntryCount >= kMaxEntries) {
        // Full: the oldest revived snapshot goes first, else the oldest of all.
        unsigned drop = 0;
        for (unsigned i = 0; i < EntryCount; ++i)
            if (I32(Entries[i], E_STATE) == STATE_REVIVED) { drop = i; break; }
        for (unsigned i = drop; i + 1 < EntryCount; ++i) Copy(Entries[i], Entries[i + 1], kEntry);
        --EntryCount;
    }
    unsigned char *e = Entries[EntryCount++];
    Zero(e, kEntry);
    VF1Revive_Status.entries = EntryCount;
    return e;
}

// ---- the capture, at every death (both ReportDeath calls; the first one wins)
static void Capture(const unsigned char *v) {
    if (!v || I32(v, REV_VILLAGER_HEALTH) > 0) return;            // only the dead
    int slot = SlotOf(v);
    if (slot < 0) return;
    for (unsigned i = 0; i < EntryCount; ++i) {
        const unsigned char *e = Entries[i];
        if (I32(e, E_STATE) == STATE_DEAD && I32(e, E_SLOT) == slot && IsPerson(e, v)
            && I32(e, E_BIO + BIO_AGE) == I32(v, REV_VILLAGER_AGE))
            return;                                                // already taken (the death behaviour's call)
    }
    unsigned char *e = NewEntry();
    W32(e, E_STATE, STATE_DEAD);
    W32(e, E_SOURCE, SOURCE_CAPTURED);
    unsigned long long marks = 0;
    for (int f = 0; f < FIELD_COUNT; ++f) marks |= (unsigned long long)MARK_EXACT << (2 * f);
    *(unsigned long long *)(e + E_MARKS) = marks;
    W32(e, E_SLOT, slot);
    W32(e, E_GENERATION, Generations());
    W32(e, E_REVIVED_SLOT, -1);
    FILETIME now;
    GetSystemTimeAsFileTime(&now);
    Copy(e + E_TIME, &now, 8);
    Copy(e + E_BIO, v + REV_VILLAGER_BIO, REV_VILLAGER_BIO_SIZE);
    Copy(e + E_VSTATE, v + REV_VILLAGER_STATE, REV_VILLAGER_STATE_SIZE);
    Copy(e + E_SKILLS, v + REV_VILLAGER_SKILLS, REV_VILLAGER_SKILLS_SIZE);
    Copy(e + E_LIKES, v + REV_VILLAGER_LIKES, REV_VILLAGER_LIKES_SIZE);
    int role = -1;
    unsigned char *rec = CurrentFamily();
    const char *name = (const char *)(v + REV_VILLAGER_NAME);
    int sex = I32(v, REV_VILLAGER_GENDER);
    if (rec) {
        Copy(e + E_PARENT1, Peep(rec, 0), REV_PEEP_RECORD_SIZE);
        Copy(e + E_PARENT2, Peep(rec, 1), REV_PEEP_RECORD_SIZE);
        int n = 2 + StockChildren(rec);
        for (int k = 0; k < n && role < 0; ++k) {
            unsigned char *peep = Peep(rec, k);
            if (PeepIs(peep, name, sex) && I32(peep, REV_PEEP_SLOT) == slot) {
                role = k;
                Copy(e + E_PEEP, peep, REV_PEEP_RECORD_SIZE);
            }
        }
        if (role < 0) {
            KidsExtraFn extra = (KidsExtraFn)Companion(L"vf1kids.dll", "VF1Kids_IsExtraChild");
            if (extra && extra(slot, sex, name)) role = 8;
        }
    }
    W32(e, E_ROLE, role);
    const char *whole = name;
    FullNameFn full = (FullNameFn)TextFunction("VF1Text_FullName");
    char field[32];
    Copy(field, name, REV_VILLAGER_NAME_LEN);
    field[REV_VILLAGER_NAME_LEN] = 0;
    if (full) whole = full(field);
    if (!whole) whole = field;
    unsigned w = Length(whole);
    if (w >= E_WHOLE_SIZE) w = E_WHOLE_SIZE - 1;
    Copy(e + E_WHOLE, whole, w);
    SkinToneOfFn toneOf = (SkinToneOfFn)Companion(L"vf1skin.dll", "VF1Skin_ToneOf");
    if (toneOf) {
        int birth = 0, tone = toneOf(slot, &birth);
        e[E_SKIN] = (unsigned char)tone;
        e[E_SKIN + 1] = (unsigned char)birth;
    }
    ++VF1Revive_Status.captured;
}

static void __fastcall DeathEndHook(void *tree, void *, void *villager) {
    Capture((const unsigned char *)villager);
    NextDeathEnd(tree, villager);
}

static void __fastcall BodyRemovalHook(void *tree, void *, void *villager) {
    Capture((const unsigned char *)villager);
    NextBodyRemoval(tree, villager);
}

// ================================================================ the sidecar
// The Up to 28 Children sidecar's layout (vf1kids.cpp) with its own tag: "VF1REVV\0", version 1, "VF1V101\0", file
// size, save file FNV-1a 64 and size, generations, parent 1 slot and gender, entry count, the entries (kEntry bytes
// each), FNV-1a 64 of everything before it.
static const unsigned kHeader = 52;
static const unsigned kMaxFile = kHeader + kMaxEntries * kEntry + 8;
static const unsigned kVersion = 1;
static unsigned char FileBuffer[kMaxFile];
static unsigned char ReadBuffer[0x10000];

struct Sidecar {
    unsigned long long saveHash;
    unsigned saveSize;
    int generations;
    int parentSlot;
    int parentGender;
    unsigned count;
    unsigned char entries[kMaxEntries][kEntry];
};
static Sidecar Loaded, BackupFile, MineFile, OldFile;

static const unsigned long long kFnvBasis = 0xCBF29CE484222325ull;
static const unsigned long long kFnvPrime = 0x100000001B3ull;

static unsigned long long Fnv(unsigned long long h, const unsigned char *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) { h ^= p[i]; h *= kFnvPrime; }
    return h;
}

static void Put32(unsigned char *p, unsigned v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24); }
static unsigned Get32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24); }

enum { FILE_MISSING = 0, FILE_OK = 1, FILE_DAMAGED = -1, FILE_SHUT = -2, FILE_FOREIGN = -3 };

static const unsigned kOpenTries = 5;
static const DWORD kOpenWaitMs = 250;

static bool Transient(DWORD e) {
    return e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION || e == ERROR_ACCESS_DENIED;
}

static HANDLE OpenForRead(const char *path, DWORD *error) {
    for (unsigned k = 0;; ++k) {
        HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
        if (h != INVALID_HANDLE_VALUE) { *error = 0; return h; }
        DWORD e = GetLastError();
        if (!Transient(e) || k + 1 >= kOpenTries) { *error = e; return h; }
        Sleep(kOpenWaitMs);
    }
}

static int OpenFailure(DWORD e) {
    return e == ERROR_FILE_NOT_FOUND || e == ERROR_PATH_NOT_FOUND ? FILE_MISSING : FILE_SHUT;
}

static int HashFile(const char *path, unsigned long long *hash, unsigned *size) {
    DWORD error = 0;
    HANDLE h = OpenForRead(path, &error);
    if (h == INVALID_HANDLE_VALUE) return OpenFailure(error);
    unsigned long long v = kFnvBasis;
    unsigned total = 0;
    int r = FILE_OK;
    for (;;) {
        DWORD got = 0;
        if (!ReadFile(h, ReadBuffer, sizeof(ReadBuffer), &got, 0)) { r = FILE_SHUT; break; }
        if (!got) break;
        v = Fnv(v, ReadBuffer, got);
        total += got;
    }
    CloseHandle(h);
    *hash = v;
    *size = total;
    return r;
}

static const unsigned kSidecarPathCap = MAX_PATH + 64;

static bool SidecarPath(void *state, int slot, char *out, unsigned cap, char *saveOut, char *folder) {
    if (!state) return false;
    void **vtable = *(void ***)state;
    const char *save = ((MakePathFn)vtable[REV_LDW_PATH_VSLOT / 4])(state, slot);
    if (!save) return false;
    unsigned n = Length(save);
    if (n == 0 || n + 1 >= MAX_PATH) return false;
    if (saveOut) Copy(saveOut, save, n + 1);
    unsigned cut = n;
    while (cut > 0 && save[cut - 1] != '\\' && save[cut - 1] != '/') --cut;
    if (cut == 0 || cut == n) return false;
    static const char middle[] = "Virtual Families 1 Patcher Data\\Revive\\";
    unsigned m = sizeof(middle) - 1;
    if (n + m + 5 >= cap) return false;
    Copy(out, save, cut);
    Copy(out + cut, middle, m);
    if (folder) {
        Copy(folder, out, cut + m - 1);
        folder[cut + m - 1] = 0;
    }
    Copy(out + cut + m, save + cut, n - cut);
    Copy(out + cut + m + (n - cut), ".dat", 5);
    return true;
}

static void EnsureFolders(const char *revive) {
    char path[MAX_PATH];
    unsigned n = Length(revive);
    if (n + 1 >= MAX_PATH) return;
    Copy(path, revive, n + 1);
    unsigned cut = n;
    while (cut > 0 && path[cut - 1] != '\\') --cut;
    if (cut > 1) {
        path[cut - 1] = 0;
        CreateDirectoryA(path, 0);
        path[cut - 1] = '\\';
    }
    CreateDirectoryA(path, 0);
}

static int ReadSidecar(const char *path, Sidecar *out) {
    DWORD error = 0;
    HANDLE h = OpenForRead(path, &error);
    if (h == INVALID_HANDLE_VALUE) return OpenFailure(error);
    DWORD got = 0;
    BOOL ok = ReadFile(h, FileBuffer, kMaxFile, &got, 0);
    DWORD more = 0;
    unsigned char extra[1];
    BOOL okMore = TRUE;
    if (ok && got == kMaxFile) okMore = ReadFile(h, extra, 1, &more, 0);
    CloseHandle(h);
    if (!ok || !okMore) return FILE_SHUT;
    if (more) return FILE_DAMAGED;
    static const unsigned char magic[8] = { 'V', 'F', '1', 'R', 'E', 'V', 'V', 0 };
    static const unsigned char tag[8] = { 'V', 'F', '1', 'V', '1', '0', '1', 0 };
    if (got < kHeader + 8) return FILE_DAMAGED;
    for (unsigned k = 0; k < 8; ++k) if (FileBuffer[k] != magic[k] || FileBuffer[12 + k] != tag[k]) return FILE_DAMAGED;
    if (Get32(FileBuffer + 8) != kVersion || Get32(FileBuffer + 20) != got) return FILE_DAMAGED;
    unsigned count = Get32(FileBuffer + 48);
    if (count > kMaxEntries || got != kHeader + count * kEntry + 8) return FILE_DAMAGED;
    unsigned long long sum = Fnv(kFnvBasis, FileBuffer, got - 8);
    if (Get32(FileBuffer + got - 8) != (unsigned)sum || Get32(FileBuffer + got - 4) != (unsigned)(sum >> 32))
        return FILE_DAMAGED;
    for (unsigned i = 0; i < count; ++i) {
        const unsigned char *p = FileBuffer + kHeader + i * kEntry;
        int state = (int)Get32(p + E_STATE), slot = (int)Get32(p + E_SLOT);
        if (state != STATE_DEAD && state != STATE_REVIVED) return FILE_DAMAGED;
        if (slot < -1 || slot >= (int)REV_HOUSEHOLD_SLOTS || p[E_WHOLE + E_WHOLE_SIZE - 1] != 0) return FILE_DAMAGED;
    }
    out->saveHash = Get32(FileBuffer + 24) | ((unsigned long long)Get32(FileBuffer + 28) << 32);
    out->saveSize = Get32(FileBuffer + 32);
    out->generations = (int)Get32(FileBuffer + 36);
    out->parentSlot = (int)Get32(FileBuffer + 40);
    out->parentGender = (int)Get32(FileBuffer + 44);
    out->count = count;
    Copy(out->entries, FileBuffer + kHeader, count * kEntry);
    return FILE_OK;
}

static bool WriteSidecar(const char *path, const char *folder, unsigned long long saveHash, unsigned saveSize) {
    unsigned char *rec = CurrentFamily();
    unsigned size = kHeader + EntryCount * kEntry + 8;
    Zero(FileBuffer, kHeader);
    Copy(FileBuffer, "VF1REVV\0", 8);
    Put32(FileBuffer + 8, kVersion);
    Copy(FileBuffer + 12, "VF1V101\0", 8);
    Put32(FileBuffer + 20, size);
    Put32(FileBuffer + 24, (unsigned)saveHash);
    Put32(FileBuffer + 28, (unsigned)(saveHash >> 32));
    Put32(FileBuffer + 32, saveSize);
    Put32(FileBuffer + 36, (unsigned)Generations());
    Put32(FileBuffer + 40, rec ? (unsigned)I32(rec, REV_RECORD_PARENT1 + REV_PEEP_SLOT) : 0xFFFFFFFFu);
    Put32(FileBuffer + 44, rec ? (unsigned)I32(rec, REV_RECORD_PARENT1 + REV_PEEP_GENDER) : 0xFFFFFFFFu);
    Put32(FileBuffer + 48, EntryCount);
    Copy(FileBuffer + kHeader, Entries, EntryCount * kEntry);
    unsigned long long sum = Fnv(kFnvBasis, FileBuffer, size - 8);
    Put32(FileBuffer + size - 8, (unsigned)sum);
    Put32(FileBuffer + size - 4, (unsigned)(sum >> 32));
    EnsureFolders(folder);
    char temp[kSidecarPathCap + 8];
    unsigned n = Length(path);
    if (n + 5 > sizeof(temp)) return false;
    Copy(temp, path, n);
    Copy(temp + n, ".tmp", 5);
    HANDLE h = CreateFileA(temp, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    BOOL ok = WriteFile(h, FileBuffer, size, &written, 0) && written == size;
    if (ok) ok = FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok) { DeleteFileA(temp); return false; }
    if (!MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) { DeleteFileA(temp); return false; }
    return true;
}

static bool MoveAside(const char *path) {
    char aside[kSidecarPathCap + 32];
    unsigned n = Length(path);
    if (n < 4 || n + 17 > sizeof(aside)) return false;
    Copy(aside, path, n - 4);
    for (unsigned k = 1; k < 1000; ++k) {
        unsigned m = n - 4;
        static const char mid[] = ".unreadable-";
        Copy(aside + m, mid, sizeof(mid) - 1);
        m += sizeof(mid) - 1;
        char digits[4];
        unsigned d = 0, v = k;
        do { digits[d++] = (char)('0' + v % 10); v /= 10; } while (v);
        while (d) aside[m++] = digits[--d];
        Copy(aside + m, ".dat", 5);
        if (MoveFileExA(path, aside, 0)) return true;
        if (GetLastError() != ERROR_ALREADY_EXISTS && GetLastError() != ERROR_FILE_EXISTS) return false;
    }
    return false;
}

static bool SameFamily(const Sidecar &file) {
    unsigned char *rec = CurrentFamily();
    if (!rec) return false;
    return file.generations == Generations()
        && file.parentSlot == I32(rec, REV_RECORD_PARENT1 + REV_PEEP_SLOT)
        && file.parentGender == I32(rec, REV_RECORD_PARENT1 + REV_PEEP_GENDER);
}

static bool Held(const unsigned char *e, unsigned upTo) {
    for (unsigned j = 0; j < upTo; ++j) {
        const unsigned char *h = Entries[j];
        if (I32(h, E_SLOT) == I32(e, E_SLOT) && Same(h + E_BIO, e + E_BIO, REV_VILLAGER_BIO_SIZE)) return true;
    }
    return false;
}

// The file's entries join the ones held now, less any already held. `exact`: the file was written with this very
// save, so all of it is kept; otherwise (another save of this family) only the dead who are not alive now.
static void Merge(const Sidecar &file, bool exact) {
    unsigned held = EntryCount;
    for (unsigned i = 0; i < file.count && EntryCount < kMaxEntries; ++i) {
        const unsigned char *e = file.entries[i];
        if (Held(e, held)) continue;
        if (!exact && (I32(e, E_STATE) != STATE_DEAD || AliveNow(e))) continue;
        Copy(Entries[EntryCount++], e, kEntry);
    }
    VF1Revive_Status.entries = EntryCount;
}

static int Describes(const Sidecar &file, const char *save) {
    unsigned long long hash = 0;
    unsigned size = 0;
    int h = HashFile(save, &hash, &size);
    if (h == FILE_SHUT) return FILE_SHUT;
    return h == FILE_OK && file.saveHash == hash && file.saveSize == size ? FILE_OK : FILE_FOREIGN;
}

static int Classify(const char *path, const char *save, Sidecar *out) {
    int r = ReadSidecar(path, out);
    return r == FILE_OK ? Describes(*out, save) : r;
}

static int ShutSlot = -1;

static void AfterLoad(void *state, int slot) {
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    ShutSlot = -1;
    ClearEntries();
    GenerationsSeen = Generations();
    if (!SidecarPath(state, slot, path, sizeof(path), save, folder)) return;
    unsigned long long hash = 0;
    unsigned size = 0;
    bool hashed = HashFile(save, &hash, &size) == FILE_OK;
    int r = ReadSidecar(path, &Loaded);
    VF1Revive_Status.lastLoad = 4;
    if (r == FILE_SHUT) {
        ShutSlot = slot;
        VF1Revive_Status.lastLoad = 6;
        Log("slot %u: the sidecar could not be opened (in use?); it is left as it is", (unsigned)slot);
    } else if (r == FILE_DAMAGED) {
        bool moved = MoveAside(path);
        VF1Revive_Status.lastLoad = moved ? 5 : 7;
        Log(moved ? "slot %u: an unreadable sidecar was moved aside"
                  : "slot %u: an unreadable sidecar could not be moved aside; it is left as it is", (unsigned)slot);
    }
    if (r == FILE_OK && hashed && Loaded.saveHash == hash && Loaded.saveSize == size) {
        Merge(Loaded, true);
        VF1Revive_Status.lastLoad = 1;
        Log("slot %u: %u snapshots from the sidecar", (unsigned)slot, EntryCount);
        return;
    }
    // The game's own backup (slot + 20) is the previous save: a restored backup has its sidecar there.
    if (hashed && SidecarPath(state, slot + (int)REV_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0)
        && ReadSidecar(backup, &BackupFile) == FILE_OK && BackupFile.saveHash == hash && BackupFile.saveSize == size) {
        Merge(BackupFile, true);
        if (r != FILE_SHUT) VF1Revive_Status.lastLoad = 2;
        Log("slot %u: %u snapshots from the backup's sidecar", (unsigned)slot, EntryCount);
        return;
    }
    if (r == FILE_OK && SameFamily(Loaded)) {
        Merge(Loaded, false);
        VF1Revive_Status.lastLoad = 3;
        Log("slot %u: the sidecar is for another save of this family; kept the %u dead not alive in this save",
            (unsigned)slot, EntryCount);
    }
}

static bool __fastcall GameStateLoad(void *state, void *, int slot) {
    bool loaded = NextLoad(state, slot);
    if (loaded && slot >= 1 && slot <= 5) AfterLoad(state, slot);
    return loaded;
}

// vf1kids.cpp RotateSidecars, for this folder: only a sidecar that validated and belongs to its save is rotated with
// it (or removed with it); a damaged or foreign one is set aside; a shut one is left as it is, and while this slot's is
// shut none is written for it.
static bool RotateSidecars(int slot, const char *path, const char *save, const char *backup, const char *backupSave) {
    int mine = Classify(path, save, &MineFile);
    bool backups = mine == FILE_FOREIGN && Describes(MineFile, backupSave) == FILE_OK;
    if (ShutSlot == slot && mine != FILE_SHUT) {
        if (mine == FILE_OK || backups) Merge(MineFile, true);
        else if (mine == FILE_FOREIGN && SameFamily(MineFile)) Merge(MineFile, false);
        ShutSlot = -1;
    }
    if (mine == FILE_SHUT || ShutSlot == slot) {
        Log("slot %u: the sidecar could not be opened (in use?); it is left as it is", (unsigned)slot);
        return false;
    }
    int old = Classify(backup, backupSave, &OldFile);
    bool clear = old == FILE_MISSING;
    if (old == FILE_OK) clear = DeleteFileA(backup) != 0;
    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = MoveAside(backup);
    if (mine == FILE_OK) {
        if (clear) MoveFileExA(path, backup, 0);
    } else if (backups) {
        DeleteFileA(path);
    } else if (mine == FILE_DAMAGED || mine == FILE_FOREIGN) {
        if (!MoveAside(path)) {
            Log("slot %u: a sidecar could not be moved aside; it is left as it is", (unsigned)slot);
            return false;
        }
    }
    return true;
}

static bool __fastcall GameStateSave(void *state, void *, int slot) {
    if (slot <= 0) return NextSave(state, slot);
    // A new family (Start Over, a new player, Evict Family): the tree began again, the old family's dead are not
    // this family's.
    if (Generations() < GenerationsSeen) ClearEntries();
    GenerationsSeen = Generations();
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    bool named = SidecarPath(state, slot, path, sizeof(path), save, folder)
        && SidecarPath(state, slot + (int)REV_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0);
    bool writable = named && RotateSidecars(slot, path, save, backup, backupSave);
    bool saved = NextSave(state, slot);
    if (!saved || !named) return saved;
    if (!writable) { VF1Revive_Status.lastSave = 4; return saved; }
    if (!EntryCount) { VF1Revive_Status.lastSave = 2; return saved; }
    unsigned long long hash = 0;
    unsigned size = 0;
    if (HashFile(save, &hash, &size) == FILE_OK && WriteSidecar(path, folder, hash, size)) {
        VF1Revive_Status.lastSave = 1;
    } else {
        VF1Revive_Status.lastSave = 3;
        Log("slot %u: the sidecar could not be written", (unsigned)slot);
    }
    return saved;
}

// ================================================================ reviving
// Why someone cannot be revived now (vf1fun's Family page shows it), or REVIVE_OK.
enum { REVIVE_OK = 0, REVIVE_NOT_DEAD = 1, REVIVE_EARLIER_GENERATION = 2, REVIVE_ALIVE = 3, REVIVE_HOUSE_FULL = 4,
       REVIVE_AGE_UNKNOWN = 5, REVIVE_NO_SUCH = 6, REVIVE_FAILED = 7, REVIVE_NO_FAMILY = 8 };
// How they came back.
// BACK_FAMILY_MEMBER: in the house, in no Family Tree entry (a child whose entry is gone, a parent of then whose
// partner is no longer parent 1).
// BACK_UNDER_SPOUSE: a spouse whose partner has remarried (the owner, 2026-11-26): a family member in the house,
// in no Family Tree entry and no child place, DRAWN on the game's Family Tree screen under the current spouse
// (TreeRowDetour below) and opened with a click as a tree person is.
enum { BACK_CHILD = 1, BACK_EXTRA_CHILD = 2, BACK_PARENT = 3, BACK_SPOUSE = 4, BACK_FAMILY_MEMBER = 5,
       BACK_UNDER_SPOUSE = 7 };

// The age they come back at, in the game's own age units (the owner, 2026-11-26, final): died younger than 20 ->
// the age they died at (18 and 19 included); died at 20 or older -> exactly 20 (400 units), with their career; an
// age at death the backfill could not find ("unknown -> 20") -> 20.
static const int kAdultUnits = (int)(REV_REVIVE_ADULT_YEARS * REV_UNITS_PER_YEAR);

static bool DiedGrownUp(const unsigned char *e) {
    unsigned mark = Mark(e, FIELD_AGE);
    return mark == MARK_UNKNOWN || mark == MARK_UNKNOWN_ADULT || I32(e, E_BIO + BIO_AGE) >= kAdultUnits;
}

static int ReviveAge(const unsigned char *e) {
    if (DiedGrownUp(e)) return kAdultUnits;
    int age = I32(e, E_BIO + BIO_AGE);
    return age < 0 ? 0 : age;
}

// ---- a revived grown-up with no career
// Someone brought back at 20 (they died at 20 or older) who had no career is a grown-up all the same (the owner): the
// at-19 college exit is not theirs (at 0x489EAC the ageing pass asks CVillagerSkills::HasCareer and leaves only on
// 0; at 20 they are past it, and this call answers "has a career" for them), and they can be the mother or father of
// a baby (below). A revived 18- or 19-year-old follows the game's own rules, the college exit included. Every other
// HasCareer call (jobs, salary, the events) is the game's own.
typedef int (__thiscall *HasCareerFn)(void *skills);
static HasCareerFn NextHasCareerAt19;

static bool RevivedGrownUp(const unsigned char *v, int slot) {
    if (!v || !v[REV_VILLAGER_PRESENT]) return false;
    for (unsigned i = 0; i < EntryCount; ++i) {
        const unsigned char *e = Entries[i];
        if (I32(e, E_STATE) == STATE_REVIVED && I32(e, E_REVIVED_SLOT) == slot && DiedGrownUp(e)
            && NameEquals((const char *)(v + REV_VILLAGER_NAME), (const char *)(e + E_BIO + BIO_NAME))
            && I32(v, REV_VILLAGER_GENDER) == I32(e, E_BIO + BIO_SEX))
            return true;
    }
    return false;
}

static int __fastcall HasCareerAt19(void *skills, void *) {
    const unsigned char *v = (const unsigned char *)skills - REV_VILLAGER_SKILLS;
    int slot = SlotOf(v);
    int has = NextHasCareerAt19(skills);
    if (!has && slot >= 0 && RevivedGrownUp(v, slot)) return 1;
    return has;
}

// ---- babies: a revived spouse or parent with no career can be the mother or father of a pregnancy (the owner,
// 2026-11-26). The game lets only villagers with a career have a baby, in two places, and only those are changed:
//   * a drop on the spouse (0x44123D, 0x441250): both must have a career -- the same answer as at 19;
//   * the try-for-a-baby step (0x48EB40, 0x48EB4C): the mother is GetMatriarch, the father GetPatriarch -- the first
//     villager in slot order at home, present, alive, with a career, of that sex. Here the same rule is run with
//     "has a career" true for a revived grown-up too. With no revived grown-up in the house the game's own function
//     answers (what was there: the stock one, or a companion's wrapper).
// GetMatriarch and GetPatriarch's other callers (the events, the dating scene, the Family page) are not changed.
typedef void *(__thiscall *PickFn)(void *manager);
static PickFn NextMother, NextFather;
static HasCareerFn NextPairA, NextPairB;

static int __fastcall HasCareerPairA(void *skills, void *) {
    const unsigned char *v = (const unsigned char *)skills - REV_VILLAGER_SKILLS;
    int has = NextPairA(skills), slot = SlotOf(v);
    return !has && slot >= 0 && RevivedGrownUp(v, slot) ? 1 : has;
}

static int __fastcall HasCareerPairB(void *skills, void *) {
    const unsigned char *v = (const unsigned char *)skills - REV_VILLAGER_SKILLS;
    int has = NextPairB(skills), slot = SlotOf(v);
    return !has && slot >= 0 && RevivedGrownUp(v, slot) ? 1 : has;
}

static void *Parent(void *manager, int sex, PickFn next) {
    bool any = false;
    for (int s = 0; s < (int)REV_HOUSEHOLD_SLOTS && !any; ++s) any = RevivedGrownUp(Villager(s), s);
    if (!any) return next(manager);
    for (int s = 0; s < (int)REV_HOUSEHOLD_SLOTS; ++s) {
        unsigned char *v = Villager(s);
        if (!v[REV_VILLAGER_PRESENT] || v[REV_VILLAGER_LEFT_HOME] || I32(v, REV_VILLAGER_HEALTH) <= 0) continue;
        if (!((HasCareerFn)REV_V_HAS_CAREER)(v + REV_VILLAGER_SKILLS) && !RevivedGrownUp(v, s)) continue;
        if (I32(v, REV_VILLAGER_GENDER) == sex) return v;
    }
    return 0;
}

static void *__fastcall BabyMother(void *manager, void *) { return Parent(manager, 1, NextMother); }
static void *__fastcall BabyFather(void *manager, void *) { return Parent(manager, 0, NextFather); }

// Their generation is the current one: the same generation number, and the family's parent 1 is still the one
// recorded at the death, or (a founder who died childless: the spouse took the founder's place) the spouse recorded.
static bool CurrentGeneration(const unsigned char *e) {
    unsigned char *rec = CurrentFamily();
    if (!rec || I32(e, E_GENERATION) != Generations()) return false;
    const unsigned char *p1 = Peep(rec, 0);
    if (!p1[REV_PEEP_VALID]) return false;
    for (unsigned off = E_PARENT1; off <= E_PARENT2; off += E_PARENT2 - E_PARENT1) {
        const unsigned char *was = e + off;
        if (was[REV_PEEP_VALID] && PeepIs(p1, (const char *)was, I32(was, REV_PEEP_GENDER))) return true;
    }
    return false;
}

static int FreePlaces() {
    const unsigned char *gs = GameState();
    int n = 0;
    for (int s = 0; s < (int)REV_HOUSEHOLD_SLOTS; ++s) {
        if (Villager(s)[REV_VILLAGER_PRESENT]) continue;
        bool reserved = false;
        for (int k = 0; gs && k < 3; ++k) reserved |= I32(gs, REV_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) == s;
        if (!reserved) ++n;
    }
    return n;
}

static int Check(unsigned i) {
    if (i >= EntryCount) return REVIVE_NO_SUCH;
    const unsigned char *e = Entries[i];
    if (I32(e, E_STATE) != STATE_DEAD) return REVIVE_NOT_DEAD;
    if (!CurrentFamily()) return REVIVE_NO_FAMILY;
    if (!CurrentGeneration(e)) return REVIVE_EARLIER_GENERATION;
    if (AliveNow(e)) return REVIVE_ALIVE;
    if (FreePlaces() <= 0) return REVIVE_HOUSE_FULL;
    return REVIVE_OK;
}

// The snapshot's persistent fields over the new villager (the field marks say which are known), then read back.
static bool WriteBack(unsigned char *v, const unsigned char *e, const char *stored) {
    const unsigned char *bio = e + E_BIO, *st = e + E_VSTATE;
    unsigned char *vb = v + REV_VILLAGER_BIO, *vs = v + REV_VILLAGER_STATE;
    for (int pass = 0; pass < 2; ++pass) {
        bool write = pass == 0, ok = true;
        struct Part { int field; unsigned char *to; const unsigned char *from; unsigned n; };
        const Part parts[] = {
            { FIELD_NAME, vb + BIO_NAME, (const unsigned char *)stored, REV_VILLAGER_NAME_LEN },
            { FIELD_NAME_INDEX, vb + BIO_NAME_INDEX, bio + BIO_NAME_INDEX, 4 },
            { FIELD_VOICE, vb + BIO_VOICE, bio + BIO_VOICE, 4 },
            { FIELD_HEAD, vb + BIO_HEAD, bio + BIO_HEAD, 4 },
            { FIELD_BODY, vb + BIO_BODY, bio + BIO_BODY, 4 },
            { FIELD_PARENTS, vb + BIO_PARENTS, bio + BIO_PARENTS, BIO_PARENTS_SIZE },
            { FIELD_FERTILITY, vs + ST_FERTILITY, st + ST_FERTILITY, 4 },
            { FIELD_WANTS_KIDS, vs + ST_WANTS_KIDS, st + ST_WANTS_KIDS, 4 },
            { FIELD_CAREER, v + REV_VILLAGER_SKILLS, e + E_SKILLS, REV_VILLAGER_SKILLS_SIZE },
            { FIELD_LIKES, v + REV_VILLAGER_LIKES, e + E_LIKES, 12 },
            { FIELD_DISLIKES, v + REV_VILLAGER_LIKES + 12, e + E_LIKES + 12, 12 },
        };
        for (unsigned k = 0; k < sizeof(parts) / sizeof(parts[0]); ++k) {
            const Part &p = parts[k];
            if (Mark(e, p.field) == MARK_UNKNOWN) continue;          // unknown: the creator's fresh value stays
            if (write) Copy(p.to, p.from, p.n);
            else if (!Same(p.to, p.from, p.n)) ok = false;
        }
        if (!write && (!ok || I32(v, REV_VILLAGER_GENDER) != I32(bio, BIO_SEX))) return false;
    }
    return true;
}

static void TakeAway(unsigned char *v) {
    // A villager made a moment ago and not in the tree: taken out as a discarded candidate is (present 0).
    v[REV_VILLAGER_PRESENT] = 0;
}

// The Family Tree: their place again where it still waits for them; otherwise a family member.
static int OwnPlace(const unsigned char *e, int slot, const char *stored) {
    unsigned char *rec = CurrentFamily();
    const char *name = (const char *)(e + E_BIO + BIO_NAME);
    int sex = I32(e, E_BIO + BIO_SEX), role = I32(e, E_ROLE);
    if (!rec) return BACK_FAMILY_MEMBER;
    if (role >= 2 && role <= 7) {
        int n = StockChildren(rec);
        for (int k = 0; k < n; ++k) {
            unsigned char *peep = Peep(rec, 2 + k);
            if (PeepIs(peep, name, sex) && I32(peep, REV_PEEP_SLOT) == -1) {
                Copy(peep, stored, REV_VILLAGER_NAME_LEN);
                W32(peep, REV_PEEP_SLOT, slot);
                return BACK_CHILD;
            }
        }
        return BACK_FAMILY_MEMBER;
    }
    if (role == 8) {
        KidsRevivedFn revived = (KidsRevivedFn)Companion(L"vf1kids.dll", "VF1Kids_Revived");
        return revived && revived(I32(e, E_SLOT), sex, name, slot) ? BACK_EXTRA_CHILD : BACK_FAMILY_MEMBER;
    }
    if (role == 0 || role == 1) {
        for (int k = 0; k < 2; ++k) {
            unsigned char *peep = Peep(rec, k);
            if (PeepIs(peep, name, sex) && I32(peep, REV_PEEP_SLOT) == -1) {
                Copy(peep, stored, REV_VILLAGER_NAME_LEN);
                W32(peep, REV_PEEP_SLOT, slot);
                return k == 0 ? BACK_PARENT : BACK_SPOUSE;
            }
        }
        // Their entry is gone (a death with no children frees it). The spouse place is theirs again only while it is
        // empty and their partner of then is still parent 1: a partner who remarried has a spouse.
        unsigned char *p1 = Peep(rec, 0), *p2 = Peep(rec, 1);
        const unsigned char *partner = e + (role == 0 ? E_PARENT2 : E_PARENT1);
        if (!p2[REV_PEEP_VALID] && p1[REV_PEEP_VALID] && partner[REV_PEEP_VALID]
            && PeepIs(p1, (const char *)partner, I32(partner, REV_PEEP_GENDER)) && e[E_PEEP + REV_PEEP_VALID]) {
            Copy(p2, e + E_PEEP, REV_PEEP_RECORD_SIZE);
            Copy(p2, stored, REV_VILLAGER_NAME_LEN);
            W32(p2, REV_PEEP_SLOT, slot);
            return BACK_SPOUSE;
        }
        // Someone else is the spouse now: their partner remarried. A family member, in no tree entry and no child
        // place (the owner), drawn under the current spouse on the Family Tree screen.
        if (p2[REV_PEEP_VALID] && !PeepIs(p2, name, sex)) return BACK_UNDER_SPOUSE;
    }
    return BACK_FAMILY_MEMBER;
}

static int ReplaceInTree(const unsigned char *e, int slot, const char *stored) { return OwnPlace(e, slot, stored); }

// ---- the Family Tree screen: a remarried partner's late spouse, drawn under the current spouse
// The screen draws each generation's row with 0x439BA0; its spouse block (0x439D4C..0x439E7D, entered when parent
// 2 is used) draws parent 2's frame (image 0xC1) at the y in [esp+3Ch], the name (DrawString, the screen's font and
// colour) and the portrait (0x439790: sex, head, body) from the record in edi, and shades the portrait when the slot
// is -1. At the block's end (0x439E7D) the DLL runs that same block once more, for the current generation only, with
// edi a record of its own whose parent 2 is the revived person and the y one parent step lower (the step from parent
// 1 to parent 2 on this screen, [esi+74h] - [esi+6Ch] + 2), then puts the row's frame and edi back exactly and lets the
// row go on. So they are drawn with the game's own art, font and layout; no tree entry, count or heir is touched.
static unsigned char ExtraRecord[REV_FAMILY_RECORD_SIZE];
static unsigned char SavedRowFrame[0x54];
static unsigned SavedRowEdi;
static int gExtraDrawing;
extern "C" int gGoBlock = 0;
extern "C" unsigned gBlockBody = REV_TREE_BLOCK_BODY, gBlockNext = REV_TREE_BLOCK_NEXT;

// The revived person drawn under the spouse, as an SPeepRecord (their own tree entry at death, with the name and
// slot they have now), or 0.
static const unsigned char *UnderSpouse(unsigned char *peep) {
    for (unsigned i = 0; i < EntryCount; ++i) {
        const unsigned char *e = Entries[i];
        int slot = I32(e, E_REVIVED_SLOT);
        const unsigned char *v = Villager(slot);
        if (I32(e, E_STATE) != STATE_REVIVED || I32(e, E_HOW) != BACK_UNDER_SPOUSE || !v) continue;
        if (!v[REV_VILLAGER_PRESENT] || v[REV_VILLAGER_LEFT_HOME] || I32(v, REV_VILLAGER_HEALTH) <= 0) continue;
        if (I32(v, REV_VILLAGER_GENDER) != I32(e, E_BIO + BIO_SEX) || !CurrentGeneration(e)) continue;
        Zero(peep, REV_PEEP_RECORD_SIZE);
        Copy(peep, e + E_PEEP, REV_PEEP_RECORD_SIZE);
        Copy(peep, v + REV_VILLAGER_NAME, REV_VILLAGER_NAME_LEN);
        peep[REV_PEEP_VALID] = 1;
        W32(peep, REV_PEEP_GENDER, I32(v, REV_VILLAGER_GENDER));
        W32(peep, REV_PEEP_HEAD, I32(v, REV_VILLAGER_HEAD));
        W32(peep, REV_PEEP_BODY, I32(v, REV_VILLAGER_BODY));
        W32(peep, REV_PEEP_SLOT, slot);
        return peep;
    }
    return 0;
}

static int SpouseStep(const unsigned char *scene) { return I32(scene, 0x74) - I32(scene, 0x6C) + 2; }

// regs: the row's registers as pushad left them (edi, esi, ebp, esp, ebx, edx, ecx, eax).
extern "C" void __cdecl TreeRowExtra(unsigned *regs) {
    unsigned char *frame = (unsigned char *)regs[3];
    gGoBlock = 0;
    if (gExtraDrawing) {                       // the extra person is drawn: the row as it was
        Copy(frame, SavedRowFrame, sizeof(SavedRowFrame));
        regs[0] = SavedRowEdi;
        gExtraDrawing = 0;
        return;
    }
    unsigned char *rec = CurrentFamily();
    if (!rec || (unsigned char *)regs[0] != rec || !rec[REV_RECORD_PARENT2 + REV_PEEP_VALID]) return;
    if (!UnderSpouse(ExtraRecord + REV_RECORD_PARENT2)) return;
    Copy(SavedRowFrame, frame, sizeof(SavedRowFrame));
    SavedRowEdi = regs[0];
    regs[0] = (unsigned)ExtraRecord;
    *(int *)(frame + 0x3C) += SpouseStep((const unsigned char *)regs[1]);
    gExtraDrawing = 1;
    gGoBlock = 1;
}

__declspec(naked) static void TreeRowDetour() {
    __asm {
        pushad
        push esp
        call TreeRowExtra
        add esp, 4
        popad
        cmp dword ptr [gGoBlock], 0
        jne block
        mov eax, dword ptr [esi + 0x80]        // the instruction the jmp replaced
        jmp dword ptr [gBlockNext]
    block:
        jmp dword ptr [gBlockBody]
    }
}

// A click on the row (0x4393E0, x, y, generation, mouse x, mouse y): the game's own first (parent 1, parent 2, the
// children); when none is hit and the click is on the extra person's frame (the game's own hit test one parent step
// lower: the frame image's rectangle, then its pixels), the game's own person dialog for them, as a click on a tree
// person opens it (0x4394B3..0x4394EA: the dialog's constructor with the record, DoModal(scene, 0), its destructor).
typedef bool (__thiscall *TreeClickFn)(void *scene, int x, int y, int gen, int mx, int my);
static TreeClickFn NextTreeClick;
typedef void *(__thiscall *ImageGetFn)(void *manager, int id);
typedef int (__thiscall *ImageSizeFn)(void *image);
typedef bool (__thiscall *ImageHitFn)(void *image, int x, int y);
typedef void (__thiscall *DialogCtorFn)(void *dialog, void *peep);
typedef void (__thiscall *DialogModalFn)(void *dialog, void *parent, int updateParent);
typedef void (__thiscall *DialogDtorFn)(void *dialog);
typedef void *(__cdecl *ImageManagerFn)();
static __declspec(align(16)) unsigned char PersonDialog[REV_TREE_EXTRA_ROOM];
static unsigned char ClickPeep[REV_PEEP_RECORD_SIZE];

static bool __fastcall TreeClick(void *scene, void *, int x, int y, int gen, int mx, int my) {
    if (NextTreeClick(scene, x, y, gen, mx, my)) return true;
    unsigned char *rec = CurrentFamily();
    if (!rec || gen != Generations() - 1 || !rec[REV_RECORD_PARENT2 + REV_PEEP_VALID]) return false;   // gen: 0-based
    if (!UnderSpouse(ClickPeep)) return false;
    const unsigned char *s = (const unsigned char *)scene;
    void *image = ((ImageGetFn)REV_IMG_GET)(((ImageManagerFn)REV_IMG_MANAGER)(), 0xC1);
    if (!image) return false;
    int w = ((ImageSizeFn)REV_IMG_WIDTH)(image), h = ((ImageSizeFn)REV_IMG_HEIGHT)(image);
    int left = I32(s, 0x68) + x, top = I32(s, 0x6C) + y + 2 * SpouseStep(s);
    if (mx < left || mx > left + w || my < top || my > top + h) return false;
    if (!((ImageHitFn)REV_IMG_HIT)(image, mx - left, my - top)) return false;
    ((DialogCtorFn)REV_DLG_PERSON_CTOR)(PersonDialog, ClickPeep);
    ((DialogModalFn)REV_DLG_DO_MODAL)(PersonDialog, scene, 0);
    ((DialogDtorFn)REV_DLG_PERSON_DTOR)(PersonDialog);
    return true;
}

static int Revive(unsigned i, int *how) {
    int why = Check(i);
    if (why != REVIVE_OK) return -why;
    unsigned char *e = Entries[i];
    const unsigned char *bio = e + E_BIO;
    // The name: the whole name stored again (the Names file gives back its short form) when it is longer than the
    // field and the text companion is loaded; else the stored name itself.
    char stored[32];
    Zero(stored, sizeof(stored));
    Copy(stored, bio + BIO_NAME, REV_VILLAGER_NAME_LEN);
    stored[REV_VILLAGER_NAME_LEN - 1] = 0;
    const char *whole = (const char *)(e + E_WHOLE);
    StoreNameFn storeName = (StoreNameFn)TextFunction("VF1Text_StoreName");
    if (storeName && whole[0] && !NameEquals(whole, stored)) {
        char out[32];
        Zero(out, sizeof(out));
        if (storeName(whole, 24, out) > 0) Copy(stored, out, REV_VILLAGER_NAME_LEN);
    }
    const unsigned char *looks = bio + BIO_PARENTS + 0x34;       // parent 1 head, body, parent 2 head, body
    int voice = Mark(e, FIELD_VOICE) == MARK_UNKNOWN ? -1 : I32(bio, BIO_VOICE);   // -1: the creator picks one
    int slot = ((SpawnFullFn)REV_VM_SPAWN_FULL)(Manager(), voice, I32(bio, BIO_SEX), ReviveAge(e),
                                                (const char *)(bio + BIO_PARENTS), (const char *)(bio + BIO_PARENTS + 0x1A),
                                                I32(looks, 4), I32(looks, 0), I32(looks, 12), I32(looks, 8), 0, 0, 0);
    unsigned char *v = Villager(slot);
    if (!v) return -REVIVE_HOUSE_FULL;
    if (!WriteBack(v, e, stored) || I32(v, REV_VILLAGER_AGE) != ReviveAge(e)) {
        TakeAway(v);
        Log("a revival was taken back: the new villager did not read back as written");
        return -REVIVE_FAILED;
    }
    *how = ReplaceInTree(e, slot, stored);
    // The skin tone they had (a snapshot without one, or Skin Tones off: the newcomer's random tone stands).
    SkinToneGiveFn toneGive = (SkinToneGiveFn)Companion(L"vf1skin.dll", "VF1Skin_ToneGive");
    if (toneGive && e[E_SKIN]) toneGive(slot, e[E_SKIN], e[E_SKIN + 1]);
    W32(e, E_STATE, STATE_REVIVED);
    W32(e, E_REVIVED_SLOT, slot);
    W32(e, E_HOW, *how);
    ++VF1Revive_Status.revived;
    return slot;
}

// ---- for vf1fun's Family page
extern "C" __declspec(dllexport) int __cdecl VF1Revive_Count() { return (int)EntryCount; }

// out[0] state, [1] why not (REVIVE_*), [2] sex, [3] age at death (units), [4] cause, [5] generation, [6] role,
// [7] every field exact (1/0), [8] the age they come back at (units), [9] source, [10] the age is known (1/0)
extern "C" __declspec(dllexport) int __cdecl VF1Revive_Info(int i, int *out) {
    if (i < 0 || (unsigned)i >= EntryCount || !out) return 0;
    const unsigned char *e = Entries[i];
    bool exact = true;
    for (int f = 0; f < FIELD_COUNT; ++f) exact &= Mark(e, f) == MARK_EXACT;
    out[0] = I32(e, E_STATE);
    out[1] = Check((unsigned)i);
    out[2] = I32(e, E_BIO + BIO_SEX);
    out[3] = I32(e, E_BIO + BIO_AGE);
    out[4] = I32(e, E_VSTATE + ST_CAUSE);
    out[5] = I32(e, E_GENERATION);
    out[6] = I32(e, E_ROLE);
    out[7] = exact ? 1 : 0;
    out[8] = ReviveAge(e);
    out[9] = I32(e, E_SOURCE);
    out[10] = Mark(e, FIELD_AGE) == MARK_EXACT || Mark(e, FIELD_AGE) == MARK_INFERRED ? 1 : 0;
    return 1;
}

// The name as the game stores it (vf1fun draws it with its own whole-name rule).
extern "C" __declspec(dllexport) const char *__cdecl VF1Revive_Name(int i) {
    if (i < 0 || (unsigned)i >= EntryCount) return 0;
    return (const char *)(Entries[i] + E_BIO + BIO_NAME);
}

// Brings snapshot i back. Returns the new villager's slot, or -(REVIVE_*) and nothing changed. *how: BACK_*.
extern "C" __declspec(dllexport) int __cdecl VF1Revive_Revive(int i, int *how) {
    int back = BACK_FAMILY_MEMBER;
    if (i < 0) return -REVIVE_NO_SUCH;
    int slot = Revive((unsigned)i, &back);
    if (how) *how = back;
    return slot;
}

// ================================================================ verify, plan and install
static unsigned ImageEnd() {
    const unsigned char *exe = (const unsigned char *)GetModuleHandleW(0);
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)exe;
    const IMAGE_NT_HEADERS32 *nt = (const IMAGE_NT_HEADERS32 *)(exe + dos->e_lfanew);
    return (unsigned)exe + nt->OptionalHeader.SizeOfImage;
}

static bool InExe(unsigned va) { return va >= 0x400000u && va < ImageEnd(); }
static unsigned JumpTarget(unsigned at) { return at + 5 + *(const int *)(at + 1); }

static bool PinsMatch() {
    if ((unsigned)GetModuleHandleW(0) != 0x400000u) return false;
    unsigned end = ImageEnd();
    for (unsigned i = 0; i < sizeof(REV_PINS) / sizeof(REV_PINS[0]); ++i) {
        const RevivePin &p = REV_PINS[i];
        if (p.va < 0x401000u || p.va + p.len > end) return false;
        const unsigned char *live = (const unsigned char *)p.va;
        for (unsigned k = 0; k < p.len; ++k)
            if (!p.mask[k] && live[k] != p.bytes[k]) return false;
    }
    return true;
}

struct Write5 { unsigned va; unsigned char bytes[5]; unsigned char original[5]; };
struct Plan {
    Write5 writes[10];
    unsigned count;
    unsigned load, save;       // theGameState's Load and Save slots: the values they hold now
};

static void *CallHandler(unsigned i) {
    switch (i) {
    case REV_CALL_DEATH_END: return (void *)&DeathEndHook;
    case REV_CALL_BODY_REMOVAL: return (void *)&BodyRemovalHook;
    case REV_CALL_AT_19_CAREER: return (void *)&HasCareerAt19;
    case REV_CALL_BABY_MOTHER: return (void *)&BabyMother;
    case REV_CALL_BABY_FATHER: return (void *)&BabyFather;
    case REV_CALL_PAIR_CAREER_A: return (void *)&HasCareerPairA;
    case REV_CALL_PAIR_CAREER_B: return (void *)&HasCareerPairB;
    case REV_CALL_TREE_CLICK: return (void *)&TreeClick;
    }
    return 0;
}

static void SetCallNext(unsigned i, unsigned target) {
    switch (i) {
    case REV_CALL_DEATH_END: NextDeathEnd = (ReportDeathFn)target; break;
    case REV_CALL_BODY_REMOVAL: NextBodyRemoval = (ReportDeathFn)target; break;
    case REV_CALL_AT_19_CAREER: NextHasCareerAt19 = (HasCareerFn)target; break;
    case REV_CALL_BABY_MOTHER: NextMother = (PickFn)target; break;
    case REV_CALL_BABY_FATHER: NextFather = (PickFn)target; break;
    case REV_CALL_PAIR_CAREER_A: NextPairA = (HasCareerFn)target; break;
    case REV_CALL_PAIR_CAREER_B: NextPairB = (HasCareerFn)target; break;
    case REV_CALL_TREE_CLICK: NextTreeClick = (TreeClickFn)target; break;
    }
}

static bool PlanHooks(Plan &plan) {
    plan.count = 0;
    for (unsigned i = 0; i < sizeof(REV_CALL_HOOKS) / sizeof(REV_CALL_HOOKS[0]); ++i) {
        const ReviveCallHook &h = REV_CALL_HOOKS[i];
        if (*(const unsigned char *)h.site != 0xE8) return false;
        unsigned now = JumpTarget(h.site);
        if (now != h.target && InExe(now)) return false;     // the stock function, or a companion's wrapper of it
        SetCallNext(i, now);
        Write5 &w = plan.writes[plan.count++];
        w.va = h.site;
        w.bytes[0] = 0xE8;
        *(int *)(w.bytes + 1) = (int)((unsigned)CallHandler(i) - (h.site + 5));
    }
    // The tree row's spouse block ends with a jmp to TreeRowDetour (the pin proved the 6-byte mov it replaces; its
    // last byte is never reached: the detour runs that mov itself and goes on at the next instruction).
    if (*(const unsigned char *)REV_TREE_BLOCK_END != 0x8B) return false;
    Write5 &d = plan.writes[plan.count++];
    d.va = REV_TREE_BLOCK_END;
    d.bytes[0] = 0xE9;
    *(int *)(d.bytes + 1) = (int)((unsigned)&TreeRowDetour - (REV_TREE_BLOCK_END + 5));
    unsigned load = *(const unsigned *)REV_GS_VTABLE_LOAD, save = *(const unsigned *)REV_GS_VTABLE_SAVE;
    if ((load != REV_GS_LOAD && InExe(load)) || (save != REV_GS_SAVE && InExe(save))) return false;
    plan.load = load;
    plan.save = save;
    return true;
}

static bool WriteCode(unsigned va, const unsigned char *bytes, unsigned len) {
    DWORD old = 0;
    if (!VirtualProtect((void *)va, len, PAGE_EXECUTE_READWRITE, &old)) return false;
    for (unsigned i = 0; i < len; ++i) ((volatile unsigned char *)va)[i] = bytes[i];
    DWORD ignored = 0;
    BOOL restored = VirtualProtect((void *)va, len, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), (void *)va, len);
    return restored != FALSE;
}

static bool WriteSlot(unsigned va, unsigned value) {
    DWORD old = 0;
    if (!VirtualProtect((void *)va, 4, PAGE_READWRITE, &old)) return false;
    *(volatile unsigned *)va = value;
    DWORD ignored = 0;
    VirtualProtect((void *)va, 4, old, &ignored);
    return true;
}

static bool Apply(Plan &plan) {
    unsigned done = 0;
    for (; done < plan.count; ++done) {
        Write5 &w = plan.writes[done];
        Copy(w.original, (const void *)w.va, 5);
        if (!WriteCode(w.va, w.bytes, 5)) break;
    }
    NextLoad = (GameStateSlotFn)plan.load;
    NextSave = (GameStateSlotFn)plan.save;
    bool ok = done == plan.count && WriteSlot(REV_GS_VTABLE_LOAD, (unsigned)&GameStateLoad);
    if (ok && !WriteSlot(REV_GS_VTABLE_SAVE, (unsigned)&GameStateSave)) {
        WriteSlot(REV_GS_VTABLE_LOAD, plan.load);
        ok = false;
    }
    if (!ok) {
        for (unsigned j = 0; j < done; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, 5);
        return false;
    }
    return true;
}

static bool SettingOn() {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 14 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"settings.ini";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    return GetPrivateProfileIntW(L"Patches", L"Revive", 0, path) == 1;
}

extern "C" __declspec(dllexport) int __cdecl VF1Revive_Startup() {
    static bool started = false;
    if (started) return (int)VF1Revive_Status.installed;
    started = true;
    DWORD n = GetModuleFileNameW(ThisModule, Folder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    unsigned cut = n;
    while (cut > 0 && Folder[cut - 1] != L'\\') --cut;
    if (!cut) return 0;
    Folder[cut] = 0;
    bool on = SettingOn();
    VF1Revive_Status.requested = on ? 1u : 0u;
    if (!on) return 0;
    if (!PinsMatch()) { Log("the executable could not be proved: installing nothing"); return 0; }
    static Plan plan;
    if (!PlanHooks(plan)) { Log("a hooked site is not as expected: installing nothing"); return 0; }
    VF1Revive_Status.resolved = 1;
    ClearEntries();
    if (Apply(plan)) {
        VF1Revive_Status.installed = 1;
        Log("Revive a Family Member installed");
    }
    return (int)VF1Revive_Status.installed;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
