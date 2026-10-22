// vf1kids.dll -- "Up to 28 Children", the Virtual Families 1 Fun Patcher's companion for one feature.
// It is the Virtual Families 2 patcher's vf2kids_b200.dll ported to VF1's own code (same rules, same
// sidecar format with a VF1 tag). One feature, one DLL: nothing else is installed here.
//
// What it does (the owner's request): a generation may have up to 28 children instead of 6. Only the
// first 6 appear in the Family Tree, exactly as now, and every child -- the 7th to the 28th included --
// can be chosen to inherit the house in Next Generation. Twins and triplets near the limit are clamped
// by the game's own rule (EmptyOffspringSlots below), so the total never exceeds 28.
//
// Why 28: the household is the 30 villager slots of CVillagerManager (2 parents + 28 children). The
// stock Family Tree record holds exactly 6 children (0x1B8 + 6 * 0xD8 = 0x6C8, one generation record):
// a 7th written there would overwrite the next generation's record. So the stock record keeps the first
// 6, and children 7..28 are kept by this DLL in a sidecar .dat file beside each save file ("Virtual
// Families 1 Patcher Data\Children\<save file>.dat"). The save format is not changed: the extra children
// are ordinary villagers the stock save already stores.
//
// vf1fun.dll loads this DLL (when the patch setting is on) and calls VF1Kids_Startup() once, before the
// game's own Init. VF1 has no ASLR: every address is fixed (vf1kids_sites.h, proved by
// tools/vf1_kids_sites.py). Installing is: setting -> verify every pinned function byte for byte -> plan
// -> apply, all or nothing. On any difference NOTHING is written.
//
// The entry hooks are the VF2 port's (see that DLL for the reasoning), with VF1's differences:
//   * CountSurvivingChildren counts the children whose record slot is not -1 (VF1's own rule), so an extra
//     child counts while its entry is alive;
//   * GeneratePeepCandidate does not hide the candidate on show (CreateNextGenerationCandidates hides the
//     clones it makes), so the one-at-a-time engine hides each clone it makes.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "vf1kids_sites.h"

struct KidsStatus {
    unsigned magic;
    unsigned version;
    unsigned requested;
    unsigned resolved;
    unsigned installed;
    unsigned writeMask;
    unsigned extras;
    unsigned lastLoad;   // 0 none, 1 exact sidecar, 2 backup sidecar, 3 roster recovery, 4 nothing, 5 moved aside,
                         // 6 shut (in use: left as it is), 7 damaged but could not be moved aside (left as it is)
    unsigned lastSave;   // 0 none, 1 written, 2 nothing to write, 3 write failed, 4 a sidecar was shut or could
                         // not be moved aside: nothing was written or replaced
};
extern "C" __declspec(dllexport) volatile KidsStatus VF1Kids_Status = { 0x434B3156u, 1u, 0, 0, 0, 0, 0, 0, 0 };

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

// ---------------------------------------------------------------- log
static bool LogStarted;

#ifdef VF1KIDS_TEST
static void Log(const char *, unsigned = 0, unsigned = 0, const char * = 0) {}
#else
static unsigned Append(char *out, unsigned n, unsigned cap, const char *s) {
    while (s && *s && n + 1 < cap) out[n++] = *s++;
    return n;
}

static unsigned AppendNumber(char *out, unsigned n, unsigned cap, unsigned v) {
    char digits[12];
    unsigned k = 0;
    do { digits[k++] = (char)('0' + v % 10); v /= 10; } while (v && k < 11);
    while (k && n + 1 < cap) out[n++] = digits[--k];
    return n;
}

static void Log(const char *fmt, unsigned a = 0, unsigned b = 0, const char *text = 0) {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 12 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"vf1kids.log";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    char line[600];
    unsigned len = 0, which = 0;
    for (const char *f = fmt; *f && len + 2 < sizeof(line); ++f) {
        if (f[0] == '%' && f[1] == 'u') { len = AppendNumber(line, len, sizeof(line), which++ ? b : a); ++f; }
        else if (f[0] == '%' && f[1] == 's') { len = Append(line, len, sizeof(line), text); ++f; }
        else line[len++] = *f;
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

// Every pinned function is byte for byte what the vanilla game has (call displacements excepted). The
// process must be the game: its executable is mapped at 0x400000 and holds every pinned address.
static bool PinsMatch() {
    HMODULE exe = GetModuleHandleW(0);
    if ((unsigned)exe != 0x400000u) { Log("not the Virtual Families executable: installing nothing"); return false; }
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)exe;
    const IMAGE_NT_HEADERS32 *nt = (const IMAGE_NT_HEADERS32 *)((const unsigned char *)exe + dos->e_lfanew);
    unsigned end = (unsigned)exe + nt->OptionalHeader.SizeOfImage;
    for (unsigned i = 0; i < sizeof(KIDS_PINS) / sizeof(KIDS_PINS[0]); ++i) {
        const KidsPin &p = KIDS_PINS[i];
        if (p.va < (unsigned)exe + 0x1000u || p.va + p.len > end) {
            Log("pin %s is outside the executable", 0, 0, p.name);
            return false;
        }
    }
    for (unsigned i = 0; i < sizeof(KIDS_PINS) / sizeof(KIDS_PINS[0]); ++i) {
        const KidsPin &p = KIDS_PINS[i];
        const unsigned char *live = (const unsigned char *)p.va;
        for (unsigned k = 0; k < p.len; ++k) {
            if (!p.mask[k] && live[k] != p.bytes[k]) {
                Log("pin %s differs: installing nothing", 0, 0, p.name);
                return false;
            }
        }
    }
    return true;
}

// ================================================================ the game
typedef int (__thiscall *FindEmptySlotFn)(void *manager);
typedef int (__thiscall *ClonePeepFn)(void *manager, void *villager);
typedef void (__thiscall *CloneAsAdultFn)(void *dest, void *src);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);

typedef bool (__thiscall *AddOffspringFn)(void *tree, void *villager);
typedef void (__thiscall *ChangeNameFn)(void *tree, void *villager, const char *name);
typedef int (__thiscall *CountSurvivingFn)(void *tree);
typedef void (__thiscall *ReportDeathFn)(void *tree, void *villager);
typedef void (__thiscall *ResetFn)(void *tree);
typedef bool (__thiscall *StartNextGenerationFn)(void *tree, void *villager, int peep);
typedef void (__thiscall *CreateCandidatesFn)(void *scene);
typedef int (__thiscall *GetNextCandidateFn)(void *scene);
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);

static AddOffspringFn OrigAddOffspring;
static ChangeNameFn OrigChangeName;
static CountSurvivingFn OrigCountSurviving;
static ReportDeathFn OrigReportDeath;
static ResetFn OrigReset;
static StartNextGenerationFn OrigStartNextGeneration;
static CreateCandidatesFn OrigCreateCandidates;
static GetNextCandidateFn OrigGetNextCandidate;
static GameStateSlotFn OrigSave;
static GameStateSlotFn OrigLoad;

static unsigned char *Tree() { return (unsigned char *)KIDS_FAMILY_TREE; }
static unsigned char *Manager() { return (unsigned char *)KIDS_VILLAGER_MANAGER; }
static const unsigned char *GameState() { return *(const unsigned char *const *)KIDS_GAME_STATE_INSTANCE; }

static unsigned char *Villager(int slot) {
    if (slot < 0 || slot >= (int)KIDS_HOUSEHOLD_SLOTS) return 0;
    return Manager() + KIDS_VILLAGER_ARRAY_OFFSET + (unsigned)slot * KIDS_VILLAGER_STRIDE;
}

static int I32(const unsigned char *p, unsigned off) { return *(const int *)(p + off); }

static int Generations() { return I32(Tree(), 0); }

static unsigned char *CurrentFamily() {
    int gen = Generations();
    if (gen <= 0 || gen > (int)KIDS_TREE_GENERATIONS) return 0;
    unsigned char *rec = Tree() + gen * KIDS_FAMILY_RECORD_SIZE - KIDS_FAMILY_RECORD_BASE;
    return rec[0] ? rec : 0;
}

static int RawStockChildren() {
    int gen = Generations();
    if (gen <= 0 || gen > (int)KIDS_TREE_GENERATIONS) return 0;
    return I32(Tree(), gen * KIDS_FAMILY_RECORD_SIZE - KIDS_FAMILY_RECORD_BASE + KIDS_RECORD_CHILD_COUNT);
}

static int StockChildren() {
    int n = RawStockChildren();
    if (n < 0) n = 0;
    if (n > (int)KIDS_TREE_CHILDREN) n = KIDS_TREE_CHILDREN;
    return n;
}

// ================================================================ the extra children
enum { STATE_ALIVE = 1, STATE_DEAD = 2, STATE_GONE = 3 };
static const unsigned kNameBytes = 28;

struct Extra {
    int slot;
    int gender;
    int state;
    int head;
    int body;
    int age;
    char name[kNameBytes];
    char previous[kNameBytes];
};

static Extra Extras[KIDS_MAX_EXTRA_CHILDREN];
static unsigned ExtraCount;

static bool NameEquals(const char *a, const char *b) {
    for (unsigned i = 0; i < KIDS_VILLAGER_NAME_LEN; ++i) {
        if (a[i] != b[i]) return false;
        if (!a[i]) return true;
    }
    return true;
}

static void CopyName(char *dst, const char *src) {
    unsigned i = 0;
    for (; i < KIDS_VILLAGER_NAME_LEN && src[i]; ++i) dst[i] = src[i];
    for (; i < kNameBytes; ++i) dst[i] = 0;
}

static bool Matches(const Extra &e) {
    const unsigned char *v = Villager(e.slot);
    if (!v) return false;
    if (I32(v, KIDS_VILLAGER_GENDER) != e.gender) return false;
    const char *name = (const char *)(v + KIDS_VILLAGER_NAME);
    return NameEquals(name, e.name) || (e.previous[0] && NameEquals(name, e.previous));
}

static bool Present(int slot) {
    const unsigned char *v = Villager(slot);
    return v && v[KIDS_VILLAGER_PRESENT] != 0;
}

static void SetPresent(int slot, bool on) {
    unsigned char *v = Villager(slot);
    if (v) v[KIDS_VILLAGER_PRESENT] = on ? 1 : 0;
}

static void Sweep() {
    for (unsigned i = 0; i < ExtraCount; ++i)
        if (Extras[i].state == STATE_ALIVE && !Matches(Extras[i])) Extras[i].state = STATE_GONE;
    VF1Kids_Status.extras = ExtraCount;
}

static void ClearExtras() {
    ExtraCount = 0;
    Zero(Extras, sizeof(Extras));
    VF1Kids_Status.extras = 0;
}

static int FreeSlots() {
    const unsigned char *state = GameState();
    int reserved[3] = { -1, -1, -1 };
    if (state)
        for (int k = 0; k < 3; ++k) reserved[k] = I32(state, KIDS_GAME_STATE_RESERVED_BABY + 4 * k);
    int n = 0;
    for (int slot = 0; slot < (int)KIDS_HOUSEHOLD_SLOTS; ++slot) {
        if (Present(slot)) continue;
        if (slot == reserved[0] || slot == reserved[1] || slot == reserved[2]) continue;
        ++n;
    }
    return n;
}

// Children recorded this generation: the stock six and every extra entry, living or not.
extern "C" __declspec(dllexport) int __cdecl VF1Kids_Children() {
    return StockChildren() + (int)ExtraCount;
}

// The limit (vf1fun's Family page shows "Children: N of 28").
extern "C" __declspec(dllexport) int __cdecl VF1Kids_Limit() { return (int)KIDS_MAX_CHILDREN; }

// ================================================================ hooks: the Family Tree
static int __fastcall EmptyOffspringSlots(void *, void *) {
    Sweep();
    int born = StockChildren() + (int)ExtraCount;
    int room = (int)KIDS_MAX_CHILDREN - born;
    if (room < 0) room = 0;
    int free = FreeSlots();
    return room < free ? room : free;
}

static bool __fastcall AddOffspring(void *tree, void *, void *villager) {
    int gen = Generations();
    if (gen <= 0 || gen > (int)KIDS_TREE_GENERATIONS) return OrigAddOffspring(tree, villager);
    int stock = RawStockChildren();
    if (stock < (int)KIDS_TREE_CHILDREN) return OrigAddOffspring(tree, villager);
    if (stock > (int)KIDS_TREE_CHILDREN || !villager) return false;
    Sweep();
    if (ExtraCount >= KIDS_MAX_EXTRA_CHILDREN) return false;
    const unsigned char *v = (const unsigned char *)villager;
    int slot = I32(v, KIDS_VILLAGER_SLOT);
    if (slot < 0 || slot >= (int)KIDS_HOUSEHOLD_SLOTS) return false;
    for (unsigned i = 0; i < ExtraCount; ++i)
        if (Extras[i].slot == slot && Extras[i].state == STATE_ALIVE) Extras[i].state = STATE_GONE;
    Extra &e = Extras[ExtraCount++];
    Zero(&e, sizeof(e));
    e.slot = slot;
    e.gender = I32(v, KIDS_VILLAGER_GENDER);
    e.state = STATE_ALIVE;
    e.head = I32(v, KIDS_VILLAGER_HEAD);
    e.body = I32(v, KIDS_VILLAGER_BODY);
    e.age = I32(v, KIDS_VILLAGER_AGE);
    CopyName(e.name, (const char *)(v + KIDS_VILLAGER_NAME));
    VF1Kids_Status.extras = ExtraCount;
    return true;
}

// VF1 counts a recorded child as surviving while its record slot is not -1; an extra child counts while
// its entry is alive.
static int __fastcall CountSurviving(void *tree, void *) {
    int n = OrigCountSurviving(tree);
    Sweep();
    for (unsigned i = 0; i < ExtraCount; ++i)
        if (Extras[i].state == STATE_ALIVE) ++n;
    return n;
}

static void __fastcall ReportDeath(void *tree, void *, void *villager) {
    if (villager) {
        int slot = I32((const unsigned char *)villager, KIDS_VILLAGER_SLOT);
        for (unsigned i = 0; i < ExtraCount; ++i)
            if (Extras[i].state == STATE_ALIVE && Extras[i].slot == slot && Matches(Extras[i]))
                Extras[i].state = STATE_DEAD;
    }
    OrigReportDeath(tree, villager);
}

static void __fastcall ChangeName(void *tree, void *, void *villager, const char *name) {
    OrigChangeName(tree, villager, name);
    if (!villager || !name) return;
    int slot = I32((const unsigned char *)villager, KIDS_VILLAGER_SLOT);
    for (unsigned i = 0; i < ExtraCount; ++i) {
        Extra &e = Extras[i];
        if (e.state == STATE_ALIVE && e.slot == slot && Matches(e)) {
            Copy(e.previous, e.name, kNameBytes);
            CopyName(e.name, name);
        }
    }
}

// ================================================================ hooks: Next Generation
struct Engine {
    bool on;
    void *scene;
    int count;
    int cursor;
    int sources[KIDS_MAX_CHILDREN];
    int swapped;
};
static Engine Next = { false, 0, 0, -1, { 0 }, -1 };
static unsigned char ChildImage[KIDS_VILLAGER_STRIDE];
static unsigned char AdultImage[KIDS_VILLAGER_STRIDE];

static void RestoreSwappedChild() {
    if (Next.swapped < 0) return;
    unsigned char *v = Villager(Next.swapped);
    if (v) Copy(v, ChildImage, KIDS_VILLAGER_STRIDE);
    Next.swapped = -1;
}

static void EndEngine() {
    Next.on = false;
    Next.scene = 0;
    Next.count = 0;
    Next.cursor = -1;
    Next.swapped = -1;
}

static void __fastcall CreateCandidates(void *scene, void *) {
    RestoreSwappedChild();
    Sweep();
    unsigned extras = 0;
    for (unsigned i = 0; i < ExtraCount; ++i)
        if (Extras[i].state == STATE_ALIVE && Matches(Extras[i])) ++extras;
    unsigned char *rec = CurrentFamily();
    if (!extras || !rec) {
        EndEngine();
        OrigCreateCandidates(scene);
        return;
    }
    unsigned char *s = (unsigned char *)scene;
    *(int *)(s + KIDS_ADOPTION_COUNT) = 0;
    *(int *)(s + KIDS_ADOPTION_CURSOR) = -1;
    int n = 0;
    int stock = StockChildren();
    for (int c = 0; c < stock; ++c) {
        int slot = I32(rec, KIDS_RECORD_CHILDREN + (unsigned)c * KIDS_PEEP_RECORD_SIZE + KIDS_PEEP_SLOT);
        if (slot < 0 || slot >= (int)KIDS_HOUSEHOLD_SLOTS) continue;
        Next.sources[n++] = slot;
    }
    for (unsigned i = 0; i < ExtraCount && n < (int)KIDS_MAX_CHILDREN; ++i)
        if (Extras[i].state == STATE_ALIVE && Matches(Extras[i])) Next.sources[n++] = Extras[i].slot;
    Next.on = true;
    Next.scene = scene;
    Next.count = n;
    Next.cursor = -1;
    Next.swapped = -1;
    *(int *)(s + KIDS_ADOPTION_COUNT) = n > 0 ? 1 : 0;
}

static int MakeCandidate(int source) {
    unsigned char *child = Villager(source);
    if (!child) return -1;
    int free = ((FindEmptySlotFn)KIDS_VM_FIND_EMPTY)(Manager());
    int clone;
    if (free >= 0 && free != source) {
        clone = ((ClonePeepFn)KIDS_VM_CLONE_PEEP)(Manager(), child);
    } else {
        Copy(ChildImage, child, KIDS_VILLAGER_STRIDE);
        ((CloneAsAdultFn)KIDS_V_CLONE_AS_ADULT)(child, ChildImage);
        Next.swapped = source;
        clone = source;
    }
    // As CreateNextGenerationCandidates leaves its clones: hidden until Accept makes the heir present.
    if (clone >= 0) SetPresent(clone, false);
    return clone;
}

static int __fastcall GetNextCandidate(void *scene, void *) {
    if (!Next.on || scene != Next.scene || Next.count <= 0) return OrigGetNextCandidate(scene);
    RestoreSwappedChild();
    Next.cursor = Next.cursor + 1;
    if (Next.cursor < 0 || Next.cursor >= Next.count) Next.cursor = 0;
    int source = Next.sources[Next.cursor];
    int clone = MakeCandidate(source);
    unsigned char *s = (unsigned char *)scene;
    *(int *)(s + KIDS_ADOPTION_CLONES) = clone;
    *(int *)(s + KIDS_ADOPTION_SOURCES) = source;
    *(int *)(s + KIDS_ADOPTION_CURSOR) = 0;
    return clone;
}

static bool __fastcall StartNextGeneration(void *tree, void *, void *villager, int peep) {
    bool started = OrigStartNextGeneration(tree, villager, peep);
    EndEngine();
    if (started) ClearExtras();
    return started;
}

static void __fastcall ResetTree(void *tree, void *) {
    OrigReset(tree);
    RestoreSwappedChild();
    EndEngine();
    ClearExtras();
}

// ================================================================ the sidecar
// The Virtual Families 2 port's format with a VF1 tag: "VF1KIDS\0", version 1, "VF1V101\0", file size,
// save file FNV-1a 64 and size, generations, parent 1 slot and gender, entry count, 64-byte entries
// (slot, gender, state, head, body, age, name[28], reserved[12]), FNV-1a 64 of everything before it.
static const unsigned kHeader = 52;
static const unsigned kEntry = 64;
static const unsigned kMaxFile = kHeader + KIDS_MAX_EXTRA_CHILDREN * kEntry + 8;
static unsigned char FileBuffer[kMaxFile];
static unsigned char ReadBuffer[0x10000];

struct Sidecar {
    unsigned long long saveHash;
    unsigned saveSize;
    int generations;
    int parentSlot;
    int parentGender;
    unsigned count;
    Extra entries[KIDS_MAX_EXTRA_CHILDREN];
};
static Sidecar Loaded;

static const unsigned long long kFnvBasis = 0xCBF29CE484222325ull;
static const unsigned long long kFnvPrime = 0x100000001B3ull;

static unsigned long long Fnv(unsigned long long h, const unsigned char *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) { h ^= p[i]; h *= kFnvPrime; }
    return h;
}

static void Put32(unsigned char *p, unsigned v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24); }
static unsigned Get32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24); }

// What reading a file found. FILE_SHUT: it is there but could not be opened or read (another program
// holds it: a backup tool, a virus scan, a cloud sync). A shut file is never judged damaged, never set
// aside and never replaced; only a file that opened and then failed validation is damaged.
enum { FILE_MISSING = 0, FILE_OK = 1, FILE_DAMAGED = -1, FILE_SHUT = -2, FILE_FOREIGN = -3 };

static const unsigned kOpenTries = 5;          // about a second in all
static const DWORD kOpenWaitMs = 250;

static bool Transient(DWORD e) {
    return e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION || e == ERROR_ACCESS_DENIED;
}

// Opens for reading, trying a file another program holds open again a few times.
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

// Every sidecar path buffer: SidecarPath refuses a path that does not fit.
static const unsigned kSidecarPathCap = MAX_PATH + 64;

static unsigned Length(const char *s) { unsigned n = 0; while (s[n]) ++n; return n; }

static bool SidecarPath(void *state, int slot, char *out, unsigned cap, char *saveOut, char *folder) {
    if (!state) return false;
    void **vtable = *(void ***)state;
    const char *save = ((MakePathFn)vtable[KIDS_LDW_PATH_VSLOT / 4])(state, slot);
    if (!save) return false;
    unsigned n = Length(save);
    if (n == 0 || n + 1 >= MAX_PATH) return false;
    if (saveOut) Copy(saveOut, save, n + 1);
    unsigned cut = n;
    while (cut > 0 && save[cut - 1] != '\\' && save[cut - 1] != '/') --cut;
    if (cut == 0 || cut == n) return false;
    static const char middle[] = "Virtual Families 1 Patcher Data\\Children\\";
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

static void EnsureFolders(const char *children) {
    char path[MAX_PATH];
    unsigned n = Length(children);
    if (n + 1 >= MAX_PATH) return;
    Copy(path, children, n + 1);
    unsigned cut = n;
    while (cut > 0 && path[cut - 1] != '\\') --cut;
    if (cut > 1) {
        path[cut - 1] = 0;
        CreateDirectoryA(path, 0);
        path[cut - 1] = '\\';
    }
    CreateDirectoryA(path, 0);
}

// FILE_OK (read and valid), FILE_MISSING, FILE_DAMAGED (opened, failed validation) or FILE_SHUT.
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
    if (more) return -1;
    static const unsigned char magic[8] = { 'V', 'F', '1', 'K', 'I', 'D', 'S', 0 };
    static const unsigned char tag[8] = { 'V', 'F', '1', 'V', '1', '0', '1', 0 };
    if (got < kHeader + 8) return -1;
    for (unsigned k = 0; k < 8; ++k) if (FileBuffer[k] != magic[k] || FileBuffer[12 + k] != tag[k]) return -1;
    if (Get32(FileBuffer + 8) != KIDS_SIDECAR_VERSION || Get32(FileBuffer + 20) != got) return -1;
    unsigned count = Get32(FileBuffer + 48);
    if (count > KIDS_MAX_EXTRA_CHILDREN || got != kHeader + count * kEntry + 8) return -1;
    unsigned long long sum = Fnv(kFnvBasis, FileBuffer, got - 8);
    if (Get32(FileBuffer + got - 8) != (unsigned)sum || Get32(FileBuffer + got - 4) != (unsigned)(sum >> 32)) return -1;
    out->saveHash = Get32(FileBuffer + 24) | ((unsigned long long)Get32(FileBuffer + 28) << 32);
    out->saveSize = Get32(FileBuffer + 32);
    out->generations = (int)Get32(FileBuffer + 36);
    out->parentSlot = (int)Get32(FileBuffer + 40);
    out->parentGender = (int)Get32(FileBuffer + 44);
    out->count = count;
    for (unsigned i = 0; i < count; ++i) {
        const unsigned char *p = FileBuffer + kHeader + i * kEntry;
        Extra &e = out->entries[i];
        Zero(&e, sizeof(e));
        e.slot = (int)Get32(p);
        e.gender = (int)Get32(p + 4);
        e.state = (int)Get32(p + 8);
        e.head = (int)Get32(p + 12);
        e.body = (int)Get32(p + 16);
        e.age = (int)Get32(p + 20);
        for (unsigned k = 0; k < kNameBytes; ++k) e.name[k] = (char)p[24 + k];
        e.name[kNameBytes - 1] = 0;
        if (e.slot < 0 || e.slot >= (int)KIDS_HOUSEHOLD_SLOTS || e.state < STATE_ALIVE || e.state > STATE_GONE)
            return -1;
    }
    return 1;
}

static bool WriteSidecar(const char *path, const char *folder, unsigned long long saveHash, unsigned saveSize) {
    unsigned char *rec = CurrentFamily();
    unsigned size = kHeader + ExtraCount * kEntry + 8;
    Zero(FileBuffer, size);
    Copy(FileBuffer, "VF1KIDS\0", 8);
    Put32(FileBuffer + 8, KIDS_SIDECAR_VERSION);
    Copy(FileBuffer + 12, "VF1V101\0", 8);
    Put32(FileBuffer + 20, size);
    Put32(FileBuffer + 24, (unsigned)saveHash);
    Put32(FileBuffer + 28, (unsigned)(saveHash >> 32));
    Put32(FileBuffer + 32, saveSize);
    Put32(FileBuffer + 36, (unsigned)Generations());
    Put32(FileBuffer + 40, rec ? (unsigned)I32(rec, KIDS_RECORD_PARENT1 + KIDS_PEEP_SLOT) : 0xFFFFFFFFu);
    Put32(FileBuffer + 44, rec ? (unsigned)I32(rec, KIDS_RECORD_PARENT1 + KIDS_PEEP_GENDER) : 0xFFFFFFFFu);
    Put32(FileBuffer + 48, ExtraCount);
    for (unsigned i = 0; i < ExtraCount; ++i) {
        unsigned char *p = FileBuffer + kHeader + i * kEntry;
        const Extra &e = Extras[i];
        Put32(p, (unsigned)e.slot);
        Put32(p + 4, (unsigned)e.gender);
        Put32(p + 8, (unsigned)e.state);
        Put32(p + 12, (unsigned)e.head);
        Put32(p + 16, (unsigned)e.body);
        Put32(p + 20, (unsigned)e.age);
        Copy(p + 24, e.name, kNameBytes);
    }
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

// True when the file is now beside itself; false leaves it exactly where it was (it is never deleted).
static bool MoveAside(const char *path) {
    // "<path less .dat>.unreadable-NNN.dat": the path plus 16 characters at most, and the nul.
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
        && file.parentSlot == I32(rec, KIDS_RECORD_PARENT1 + KIDS_PEEP_SLOT)
        && file.parentGender == I32(rec, KIDS_RECORD_PARENT1 + KIDS_PEEP_GENDER);
}

static void Merge(const Sidecar &file, bool exact);

static void Adopt(const Sidecar &file, bool exact) {
    ClearExtras();
    Merge(file, exact);
}

// The file's entries join the ones held now, less any already held. Adopt starts from none; a save
// merges a sidecar a load found shut and could only read later.
static void Merge(const Sidecar &file, bool exact) {
    if (StockChildren() < (int)KIDS_TREE_CHILDREN) return;   // extras exist only after the stock six
    unsigned held = ExtraCount;
    for (unsigned i = 0; i < file.count && ExtraCount < KIDS_MAX_EXTRA_CHILDREN; ++i) {
        Extra e = file.entries[i];
        bool already = false;
        for (unsigned j = 0; j < held && !already; ++j)
            already = Extras[j].slot == e.slot && Extras[j].gender == e.gender && NameEquals(Extras[j].name, e.name);
        if (already) continue;
        bool found = Matches(e);
        if (e.state == STATE_ALIVE && !found) {
            if (!exact) continue;
            e.state = STATE_GONE;
        }
        if (!exact && e.state != STATE_ALIVE) continue;
        Extras[ExtraCount++] = e;
    }
    VF1Kids_Status.extras = ExtraCount;
}

// FILE_OK only when the sidecar validates and was written with `save` as it is on disk now; FILE_FOREIGN
// when it validates but belongs to another save (or to none); FILE_SHUT when either could not be read.
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

// A load found this slot's sidecar shut: it is unread, and no save replaces or moves it until it is read.
static int ShutSlot = -1;

static void AfterLoad(void *state, int slot) {
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    ShutSlot = -1;
    if (!SidecarPath(state, slot, path, sizeof(path), save, folder)) return;
    unsigned long long hash = 0;
    unsigned size = 0;
    bool hashed = HashFile(save, &hash, &size) == FILE_OK;
    int r = ReadSidecar(path, &Loaded);
    VF1Kids_Status.lastLoad = 4;
    if (r == FILE_SHUT) {
        // Held open by another program: not damaged. It is left exactly as it is and read at the next save.
        ShutSlot = slot;
        VF1Kids_Status.lastLoad = 6;
        Log("slot %u: the sidecar could not be opened (in use?); it is left as it is", (unsigned)slot);
    } else if (r == FILE_DAMAGED) {
        bool moved = MoveAside(path);
        VF1Kids_Status.lastLoad = moved ? 5 : 7;
        Log(moved ? "slot %u: an unreadable sidecar was moved aside"
                  : "slot %u: an unreadable sidecar could not be moved aside; it is left as it is", (unsigned)slot);
    }
    if (r == FILE_OK && hashed && Loaded.saveHash == hash && Loaded.saveSize == size && SameFamily(Loaded)) {
        Adopt(Loaded, true);
        VF1Kids_Status.lastLoad = 1;
        Log("slot %u: %u extra children from the sidecar", (unsigned)slot, ExtraCount);
        return;
    }
    // The game's own backup (slot + 20) is the previous save: a restored backup has its sidecar there.
    static Sidecar backupFile;
    if (hashed && SidecarPath(state, slot + (int)KIDS_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0)
        && ReadSidecar(backup, &backupFile) == FILE_OK && backupFile.saveHash == hash && backupFile.saveSize == size
        && SameFamily(backupFile)) {
        Adopt(backupFile, true);
        if (r != FILE_SHUT) VF1Kids_Status.lastLoad = 2;
        Log("slot %u: %u extra children from the backup's sidecar", (unsigned)slot, ExtraCount);
        return;
    }
    if (r == FILE_OK && SameFamily(Loaded)) {
        Adopt(Loaded, false);
        VF1Kids_Status.lastLoad = 3;
        Log("slot %u: the sidecar is for another save of this family; kept the %u children still at home",
            (unsigned)slot, ExtraCount);
    }
}

static bool __fastcall GameStateLoad(void *state, void *, int slot) {
    RestoreSwappedChild();
    bool loaded = OrigLoad(state, slot);
    if (loaded && slot > 0) AfterLoad(state, slot);
    return loaded;
}

// Before the game's own save rotates its files (it removes the save at slot + 20 and renames this slot's
// save to it), the two sidecars are checked. Only a sidecar that validated and belongs to its save is
// rotated with it (or removed with it); a damaged or foreign one is set aside; a shut one is left as it is,
// and while this slot's is shut no sidecar is written for it. Returns false when none may be written.
static bool RotateSidecars(int slot, const char *path, const char *save, const char *backup, const char *backupSave) {
    static Sidecar mineFile, oldFile;
    int mine = Classify(path, save, &mineFile);
    // Written with the save now at slot + 20 (a save was made while it was shut): it goes with that save.
    bool backups = mine == FILE_FOREIGN && Describes(mineFile, backupSave) == FILE_OK;
    if (ShutSlot == slot && mine != FILE_SHUT) {
        // First read since the load found it shut: what it holds is kept, with what this session added.
        if ((mine == FILE_OK || mine == FILE_FOREIGN) && SameFamily(mineFile))
            Merge(mineFile, mine == FILE_OK || backups);
        ShutSlot = -1;
    }
    if (mine == FILE_SHUT || ShutSlot == slot) {
        Log("slot %u: the sidecar could not be opened (in use?); it is left as it is", (unsigned)slot);
        return false;
    }
    int old = Classify(backup, backupSave, &oldFile);
    bool clear = old == FILE_MISSING;
    if (old == FILE_OK) clear = DeleteFileA(backup) != 0;       // its save is the one the game removes now
    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = MoveAside(backup);
    // old == FILE_SHUT: the backup's sidecar is left as it is
    if (mine == FILE_OK) {
        if (clear) MoveFileExA(path, backup, 0);
    } else if (backups) {
        DeleteFileA(path);                                       // validated, and its save is removed now
    } else if (mine == FILE_DAMAGED || mine == FILE_FOREIGN) {
        if (!MoveAside(path)) {
            Log("slot %u: a sidecar could not be moved aside; it is left as it is", (unsigned)slot);
            return false;
        }
    }
    return true;
}

static bool __fastcall GameStateSave(void *state, void *, int slot) {
    if (slot <= 0) return OrigSave(state, slot);
    Sweep();
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    bool named = SidecarPath(state, slot, path, sizeof(path), save, folder)
        && SidecarPath(state, slot + (int)KIDS_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0);
    bool writable = named && RotateSidecars(slot, path, save, backup, backupSave);
    unsigned char *v = Next.swapped >= 0 ? Villager(Next.swapped) : 0;
    if (v) {
        Copy(AdultImage, v, KIDS_VILLAGER_STRIDE);
        Copy(v, ChildImage, KIDS_VILLAGER_STRIDE);
    }
    bool saved = OrigSave(state, slot);
    if (v) Copy(v, AdultImage, KIDS_VILLAGER_STRIDE);
    if (!saved || !named) return saved;
    if (!writable) { VF1Kids_Status.lastSave = 4; return saved; }
    if (!ExtraCount) { VF1Kids_Status.lastSave = 2; return saved; }
    unsigned long long hash = 0;
    unsigned size = 0;
    if (HashFile(save, &hash, &size) == FILE_OK && WriteSidecar(path, folder, hash, size)) {
        VF1Kids_Status.lastSave = 1;
    } else {
        VF1Kids_Status.lastSave = 3;
        Log("slot %u: the sidecar could not be written", (unsigned)slot);
    }
    return saved;
}

// ================================================================ plan and install
static const unsigned kMaxWrites = 16;

struct HookWrite {
    unsigned va;
    unsigned char bytes[5];
    unsigned char original[5];
};

struct Plan {
    HookWrite writes[kMaxWrites];
    unsigned count;
};

__declspec(align(4096)) static unsigned char Trampolines[4096];
static unsigned TrampolineUsed;

static void *Handler(unsigned va) {
    switch (va) {
    case KIDS_FT_ADD_OFFSPRING: return (void *)&AddOffspring;
    case KIDS_FT_CHANGE_NAME: return (void *)&ChangeName;
    case KIDS_FT_COUNT_SURVIVING: return (void *)&CountSurviving;
    case KIDS_FT_EMPTY_OFFSPRING: return (void *)&EmptyOffspringSlots;
    case KIDS_FT_REPORT_DEATH: return (void *)&ReportDeath;
    case KIDS_FT_RESET: return (void *)&ResetTree;
    case KIDS_FT_START_NEXT_GEN: return (void *)&StartNextGeneration;
    case KIDS_AD_CREATE_CANDIDATES: return (void *)&CreateCandidates;
    case KIDS_AD_GET_NEXT: return (void *)&GetNextCandidate;
    case KIDS_GS_SAVE: return (void *)&GameStateSave;
    case KIDS_GS_LOAD: return (void *)&GameStateLoad;
    }
    return 0;
}

static void SetOriginal(unsigned va, void *t) {
    switch (va) {
    case KIDS_FT_ADD_OFFSPRING: OrigAddOffspring = (AddOffspringFn)t; break;
    case KIDS_FT_CHANGE_NAME: OrigChangeName = (ChangeNameFn)t; break;
    case KIDS_FT_COUNT_SURVIVING: OrigCountSurviving = (CountSurvivingFn)t; break;
    case KIDS_FT_REPORT_DEATH: OrigReportDeath = (ReportDeathFn)t; break;
    case KIDS_FT_RESET: OrigReset = (ResetFn)t; break;
    case KIDS_FT_START_NEXT_GEN: OrigStartNextGeneration = (StartNextGenerationFn)t; break;
    case KIDS_AD_CREATE_CANDIDATES: OrigCreateCandidates = (CreateCandidatesFn)t; break;
    case KIDS_AD_GET_NEXT: OrigGetNextCandidate = (GetNextCandidateFn)t; break;
    case KIDS_GS_SAVE: OrigSave = (GameStateSlotFn)t; break;
    case KIDS_GS_LOAD: OrigLoad = (GameStateSlotFn)t; break;
    }
}

static const KidsPin *PinAt(unsigned va) {
    for (unsigned i = 0; i < sizeof(KIDS_PINS) / sizeof(KIDS_PINS[0]); ++i)
        if (KIDS_PINS[i].va == va) return &KIDS_PINS[i];
    return 0;
}

static bool PlanHooks(Plan &plan) {
    plan.count = 0;
    TrampolineUsed = 0;
    for (unsigned h = 0; h < sizeof(KIDS_HOOKS) / sizeof(KIDS_HOOKS[0]); ++h) {
        const KidsHook &hook = KIDS_HOOKS[h];
        const KidsPin *pin = PinAt(hook.va);
        void *handler = Handler(hook.va);
        if (!pin || !handler || hook.steal < 5 || hook.steal > 16 || plan.count >= kMaxWrites) return false;
        for (unsigned k = 0; k < hook.steal; ++k)
            if (pin->mask[k] || ((const unsigned char *)hook.va)[k] != pin->bytes[k]) return false;
        if (!hook.replace) {
            if (TrampolineUsed + hook.steal + 5 + 15 > sizeof(Trampolines)) return false;
            unsigned char *t = Trampolines + TrampolineUsed;
            Copy(t, (const void *)hook.va, hook.steal);
            t[hook.steal] = 0xE9;
            *(int *)(t + hook.steal + 1) = (int)((hook.va + hook.steal) - ((unsigned)t + hook.steal + 5));
            SetOriginal(hook.va, t);
            TrampolineUsed += (hook.steal + 5 + 15) & ~15u;
        }
        HookWrite &w = plan.writes[plan.count++];
        w.va = hook.va;
        w.bytes[0] = 0xE9;
        *(int *)(w.bytes + 1) = (int)((unsigned)handler - (hook.va + 5));
    }
    return true;
}

static int BuildPlan(bool enabled, Plan &plan) {
    plan.count = 0;
    if (!enabled) return 0;
    if (!PinsMatch()) return -1;
    if (!PlanHooks(plan)) return -1;
    return 1;
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

static bool Apply(Plan &plan) {
    DWORD old = 0;
    if (!VirtualProtect(Trampolines, sizeof(Trampolines), PAGE_EXECUTE_READWRITE, &old)) return false;
    for (unsigned i = 0; i < plan.count; ++i) {
        HookWrite &w = plan.writes[i];
        for (unsigned j = 0; j < 5; ++j) w.original[j] = ((const unsigned char *)w.va)[j];
        if (!WriteCode(w.va, w.bytes, 5)) {
            for (unsigned j = 0; j < i; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, 5);
            VF1Kids_Status.writeMask = 0;
            return false;
        }
        VF1Kids_Status.writeMask |= 1u << i;
    }
    return true;
}

// The Fun Patcher's own settings file, [Patches] UpTo28Children=1 (vf1fun loads this DLL only then).
static bool SettingOn() {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 14 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"settings.ini";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    return GetPrivateProfileIntW(L"Patches", L"UpTo28Children", 0, path) == 1;
}

extern "C" __declspec(dllexport) int __cdecl VF1Kids_Startup() {
    static bool started = false;
    if (started) return (int)VF1Kids_Status.installed;
    started = true;
    DWORD n = GetModuleFileNameW(ThisModule, Folder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    unsigned cut = n;
    while (cut > 0 && Folder[cut - 1] != L'\\') --cut;
    if (!cut) return 0;
    Folder[cut] = 0;
    Log("vf1kids started");
    bool on = SettingOn();
    VF1Kids_Status.requested = on ? 1u : 0u;
    static Plan plan;
    int built = BuildPlan(on, plan);
    if (built == 0) { Log("Up to 28 Children is off: the game is stock"); return 0; }
    if (built < 0) { Log("the executable could not be proved: installing nothing"); return 0; }
    VF1Kids_Status.resolved = 1;
    ClearExtras();
    if (Apply(plan)) {
        VF1Kids_Status.installed = 1;
        Log("Up to 28 Children installed (%u writes)", plan.count);
    }
    return (int)VF1Kids_Status.installed;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}

#ifdef VF1KIDS_TEST
extern "C" __declspec(dllexport) void __cdecl VF1Kids_TestSetModule(unsigned module) { ThisModule = (HMODULE)module; }
extern "C" __declspec(dllexport) int __cdecl VF1Kids_TestPlan(int enabled, unsigned *out) {
    static Plan plan;
    int built = BuildPlan(enabled != 0, plan);
    out[0] = (unsigned)built;
    out[1] = built > 0 ? plan.count : 0;
    for (unsigned i = 0; built > 0 && i < plan.count; ++i) {
        out[2 + i * 3 + 0] = plan.writes[i].va;
        out[2 + i * 3 + 1] = *(unsigned *)plan.writes[i].bytes;
        out[2 + i * 3 + 2] = plan.writes[i].bytes[4];
    }
    return built;
}
extern "C" __declspec(dllexport) void __cdecl VF1Kids_TestExtras(int *out) {
    out[0] = (int)ExtraCount;
    for (unsigned i = 0; i < ExtraCount; ++i) {
        out[1 + i * 3] = Extras[i].slot;
        out[2 + i * 3] = Extras[i].gender;
        out[3 + i * 3] = Extras[i].state;
    }
}
extern "C" __declspec(dllexport) void __cdecl VF1Kids_TestEngine(int *out) {
    out[0] = Next.on ? 1 : 0;
    out[1] = Next.count;
    out[2] = Next.cursor;
    out[3] = Next.swapped;
    for (int i = 0; i < Next.count; ++i) out[4 + i] = Next.sources[i];
}
#endif
