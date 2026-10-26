// vf1logs.dll -- the "Family History" log, the Virtual Families 1 Fun Patcher's companion for one feature.
// One feature, one DLL.
//
// Virtual Families 1 keeps no history (docs/vf1-save-format.md section 3: no marriage, birth or death date,
// no earlier spouse, no twins), and its Family Tree forgets a spouse who leaves or dies before any child.
// The Family Tree Maker needs those, so this DLL writes them down as they happen, one line each, from the
// game's own memory, with the game's own words where it has them (the string table in the executable:
// "Male", "Female", the causes of death, every e-mail subject and pop-up title). Only what the family tree
// needs is written: marriages and remarriages (the current spouse), divorces, deaths with their cause,
// births (twins and triplets together), children who join, the e-mail and pop-up events with what each did
// to the family, and an eviction. Per save slot, beside the save:
//
//   <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\Family History\Family History <k>.txt
//
// Every file opens with "Family: <family name> (Save <N>)"; every line is "[YYYY-MM-DD HH:MM:SS] <event>".
// Nothing is ever rewritten; after 2000 lines the next line opens the next numbered file. A new family (the
// game's new-family adoption) and Start Over wipe that slot's folder, Backups excepted; an existing family
// whose log has no lines yet gets what its save's Family Tree holds, marked "[backfilled, no date]".
// The line formats are listed in docs/FAMILY_HISTORY.md and read by patcher/vf1_family_history.py.
//
// vf1fun.dll loads this DLL (while the FamilyHistory setting is on) at the end of its own start-up, after
// vf1kids.dll, and calls VF1Logs_Startup() once. Installing is: setting -> verify every pin (vf1logs_sites.h,
// proved by tools/vf1_logs_sites.py) -> plan -> apply, all or nothing. A function entry another companion
// already hooked (vf1kids.dll) is chained, never overwritten blindly. VF1 has no ASLR.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "vf1logs_sites.h"

struct LogsStatus {
    unsigned magic;
    unsigned version;
    unsigned requested;
    unsigned resolved;
    unsigned installed;
    unsigned writes;
    unsigned lines;       // Family History lines written this session
    unsigned lastLoad;    // 0 none, 1 log found or created, 2 backfilled
    unsigned wipes;       // slot folders wiped (Start Over, new family)
};
extern "C" __declspec(dllexport) volatile LogsStatus VF1Logs_Status = { 0x474C3156u, 2u, 0, 0, 0, 0, 0, 0, 0 };

static HMODULE ThisModule;
static wchar_t Folder[MAX_PATH];

// ================================================================ small helpers (no C runtime)
static void Copy(void *dst, const void *src, unsigned n) {
    volatile unsigned char *d = (volatile unsigned char *)dst;
    const volatile unsigned char *s = (const volatile unsigned char *)src;
    for (unsigned i = 0; i < n; ++i) d[i] = s[i];
}

static void Zero(void *dst, unsigned n) {
    volatile unsigned char *d = (volatile unsigned char *)dst;
    for (unsigned i = 0; i < n; ++i) d[i] = 0;
}

static unsigned Length(const char *s) { unsigned n = 0; while (s && s[n]) ++n; return n; }

static bool SameText(const char *a, const char *b, unsigned max) {
    for (unsigned i = 0; i < max; ++i) {
        if (a[i] != b[i]) return false;
        if (!a[i]) return true;
    }
    return true;
}

static bool StartsWith(const char *s, const char *prefix) {
    for (unsigned i = 0; prefix[i]; ++i) if (s[i] != prefix[i]) return false;
    return true;
}

// A text being built in a fixed buffer; anything past the end is dropped, never overrun.
struct Text {
    char *buf;
    unsigned cap;
    unsigned n;
    void Init(char *b, unsigned c) { buf = b; cap = c; n = 0; buf[0] = 0; }
    Text &S(const char *s) {
        while (s && *s && n + 1 < cap) buf[n++] = *s++;
        buf[n] = 0;
        return *this;
    }
    Text &Name(const char *s, unsigned max) {   // a game text field: at most `max` bytes, tabs and line ends dropped
        for (unsigned i = 0; s && i < max && s[i] && n + 1 < cap; ++i)
            if (s[i] != '\t' && s[i] != '\r' && s[i] != '\n') buf[n++] = s[i];
        buf[n] = 0;
        return *this;
    }
    Text &U(unsigned v) {
        char d[12];
        unsigned k = 0;
        do { d[k++] = (char)('0' + v % 10); v /= 10; } while (v && k < 11);
        while (k && n + 1 < cap) buf[n++] = d[--k];
        buf[n] = 0;
        return *this;
    }
    Text &I(int v) {
        if (v < 0) { S("-"); return U(0u - (unsigned)v); }
        return U((unsigned)v);
    }
    Text &Two(unsigned v) { if (v < 10) S("0"); return U(v); }
    Text &NL() { return S("\r\n"); }
};

// ================================================================ the game
typedef void (__thiscall *ThisVoidFn)(void *self);
typedef void (__thiscall *ReportDeathFn)(void *tree, void *villager);
typedef bool (__thiscall *UpdateParentsFn)(void *tree, void *a, void *b);
typedef bool (__thiscall *StartNextGenerationFn)(void *tree, void *villager, int peep);
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);
typedef void (__thiscall *DoModalFn)(void *dialog, void *parent, int updateParent);
typedef bool (__thiscall *ThisBoolFn)(void *self);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
typedef const char *(__thiscall *GetStringFn)(void *strings, int id);
typedef void *(__cdecl *SingletonFn)();

static ThisVoidFn NextPhysiology;
static ReportDeathFn NextReportDeathEnd, NextReportDeathBody;
static ThisVoidFn NextRestart;
static DoModalFn NextDoModal;
static UpdateParentsFn OrigUpdateParents;
static StartNextGenerationFn OrigStartNextGeneration;
static GameStateSlotFn NextLoad;

static unsigned char *Tree() { return (unsigned char *)LOGS_FAMILY_TREE; }
static unsigned char *Manager() { return (unsigned char *)LOGS_VILLAGER_MANAGER; }
static unsigned char *GameState() { return *(unsigned char **)LOGS_GAME_STATE_INSTANCE; }
static int I32(const unsigned char *p, unsigned off) { return *(const int *)(p + off); }

static unsigned char *Villager(int slot) {
    if (slot < 0 || slot >= (int)LOGS_HOUSEHOLD_SLOTS) return 0;
    return Manager() + LOGS_VILLAGER_ARRAY_OFFSET + (unsigned)slot * LOGS_VILLAGER_STRIDE;
}

static int SlotOf(const void *villager) {
    if (!villager) return -1;
    unsigned off = (unsigned)villager - (unsigned)(Manager() + LOGS_VILLAGER_ARRAY_OFFSET);
    if (off % LOGS_VILLAGER_STRIDE || off / LOGS_VILLAGER_STRIDE >= LOGS_HOUSEHOLD_SLOTS) return -1;
    return (int)(off / LOGS_VILLAGER_STRIDE);
}

static int Generations() {
    int g = I32(Tree(), 0);
    return g < 0 || g > (int)LOGS_TREE_GENERATIONS ? 0 : g;
}

static unsigned char *Record(int gen) {
    if (gen <= 0 || gen > (int)LOGS_TREE_GENERATIONS) return 0;
    unsigned char *rec = Tree() + (unsigned)gen * LOGS_FAMILY_RECORD_SIZE - LOGS_FAMILY_RECORD_BASE;
    return rec[0] ? rec : 0;
}

static int RecordChildren(const unsigned char *rec) {
    int n = I32(rec, LOGS_RECORD_CHILD_COUNT);
    return n < 0 ? 0 : n > (int)LOGS_TREE_CHILDREN ? (int)LOGS_TREE_CHILDREN : n;
}

static unsigned char *Peep(unsigned char *rec, int which) {    // 0 parent 1, 1 parent 2, 2.. children
    if (which == 0) return rec + LOGS_RECORD_PARENT1;
    if (which == 1) return rec + LOGS_RECORD_PARENT2;
    return rec + LOGS_RECORD_CHILDREN + (unsigned)(which - 2) * LOGS_PEEP_RECORD_SIZE;
}

static int CurrentSlot() {
    unsigned char *gs = GameState();
    if (!gs) return 0;
    int s = I32(gs, LOGS_GAME_STATE_SLOT);
    return s >= 1 && s <= 5 ? s : 0;
}

static const char *FamilyName() {
    unsigned char *gs = GameState();
    return gs ? (const char *)(gs + LOGS_GAME_STATE_FAMILY_NAME) : "";
}

// The executable's own words.
static const char *Word(int id) {
    void *strings = ((SingletonFn)LOGS_STRINGS_GET)();
    const char *s = strings ? ((GetStringFn)LOGS_STRINGS_GET_STRING)(strings, id) : 0;
    return s ? s : "";
}
static const char *SexWord(int sex) { return Word(sex == 1 ? (int)LOGS_STR_FEMALE : (int)LOGS_STR_MALE); }
static const char *CauseWord(int cause) {
    int id = (int)LOGS_STR_CAUSE_UNKNOWN + 1 + cause;      // -1 Unknown causes .. 4 Act of Nature
    if (id < (int)LOGS_STR_CAUSE_UNKNOWN || id > (int)LOGS_STR_CAUSE_LAST) id = (int)LOGS_STR_CAUSE_UNKNOWN;
    return Word(id);
}

struct Person {
    int slot;
    int sex;
    int age;
    char name[28];
};

static void Capture(const unsigned char *v, Person &p) {
    Zero(&p, sizeof(p));
    p.slot = SlotOf(v);
    if (!v) { p.slot = -1; return; }
    p.sex = I32(v, LOGS_VILLAGER_GENDER);
    p.age = I32(v, LOGS_VILLAGER_AGE);
    Copy(p.name, v + LOGS_VILLAGER_NAME, LOGS_VILLAGER_NAME_LEN);
    p.name[LOGS_VILLAGER_NAME_LEN] = 0;
}

static unsigned Years(int units) { return units < 0 ? 0u : (unsigned)units / LOGS_UNITS_PER_YEAR; }

// "Ann (Female, 26)"
static void Who(Text &t, const Person &p) {
    t.Name(p.name, LOGS_VILLAGER_NAME_LEN).S(" (").S(SexWord(p.sex)).S(", ").U(Years(p.age)).S(")");
}

// Where the villager stands in the current generation's Family Tree record: 0 parent 1, 1 parent 2,
// 2.. a child, -1 not in it. The record's slot is checked with the name, as the game's own records go stale.
static int TreeRole(const Person &p) {
    unsigned char *rec = Record(Generations());
    if (!rec || p.slot < 0) return -1;
    int n = 2 + RecordChildren(rec);
    for (int k = 0; k < n; ++k) {
        unsigned char *peep = Peep(rec, k);
        if (peep[LOGS_PEEP_VALID] && I32(peep, LOGS_PEEP_SLOT) == p.slot && SameText((const char *)peep, p.name, 25))
            return k;
    }
    return -1;
}

static const char *RoleWord(int role) {
    return role == 0 ? "parent" : role == 1 ? "spouse" : role >= 2 ? "child" : "not in the family tree";
}

// ================================================================ the Family History files
static char ReadBuffer[0x100000];
static char Line[0x4000];
static char Body[0x4000];

static const unsigned kLinesPerFile = 2000;
static const unsigned kMaxFiles = 4096;

static bool ReadWhole(const char *path, unsigned *got) {
    *got = 0;
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD n = 0;
    BOOL ok = ReadFile(h, ReadBuffer, sizeof(ReadBuffer) - 1, &n, 0);
    CloseHandle(h);
    if (!ok) return false;
    ReadBuffer[n] = 0;
    *got = n;
    return true;
}

static bool Exists(const char *path) { return GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES; }

// Every folder from the save folder's drive down to `path`'s own folder.
static void MakeParents(const char *path) {
    char p[MAX_PATH + 64];
    unsigned n = Length(path);
    if (n >= sizeof(p)) return;
    Copy(p, path, n + 1);
    for (unsigned i = 3; i < n; ++i) {
        if (p[i] == '\\') {
            p[i] = 0;
            CreateDirectoryA(p, 0);
            p[i] = '\\';
        }
    }
}

static bool Append(const char *path, const char *text, unsigned len) {
    MakeParents(path);
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, 0, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    BOOL ok = WriteFile(h, text, len, &written, 0) && written == len;
    CloseHandle(h);
    return ok != FALSE;
}

// <save folder>\ (from the game's own save path, MakeGameStatePath, theGameState vtable +0Ch).
static bool SaveFolder(char *out, unsigned cap) {
    unsigned char *state = GameState();
    if (!state) return false;
    void **vtable = *(void ***)state;
    const char *save = ((MakePathFn)vtable[LOGS_LDW_PATH_VSLOT / 4])(state, 1);
    unsigned n = Length(save);
    if (!save || n == 0 || n + 1 >= MAX_PATH) return false;
    unsigned cut = n;
    while (cut > 0 && save[cut - 1] != '\\' && save[cut - 1] != '/') --cut;
    if (cut == 0 || cut + 1 >= cap) return false;
    Copy(out, save, cut);
    out[cut] = 0;
    return true;
}

static const char kSaves[] = "Virtual Families 1 Patcher\\Save ";

// <save folder>\Virtual Families 1 Patcher\Save <slot>
static bool SlotRoot(int slot, Text &t) {
    char folder[MAX_PATH];
    if (slot < 1 || slot > 5 || !SaveFolder(folder, sizeof(folder))) return false;
    t.S(folder).S(kSaves).U((unsigned)slot);
    return t.n + 120 < t.cap;
}

static bool HistoryFile(int slot, unsigned number, char *out, unsigned cap) {
    Text t;
    t.Init(out, cap);
    if (!SlotRoot(slot, t)) return false;
    t.S("\\Logs\\Family History\\Family History ").U(number).S(".txt");
    return t.n + 8 < cap;
}

// "Family: <name> (Save <N>)" -- the header every file opens with (the Virtual Villagers logs'
// "Village: <name> (Save <S>)").
static void Header(Text &t, int slot) {
    const char *name = FamilyName();
    t.S("Family: ");
    if (name[0]) t.Name(name, LOGS_GAME_STATE_FAMILY_NAME_LEN - 1); else t.S("(no name)");
    t.S(" (Save ").U((unsigned)slot).S(")").NL();
}

// Lines of the text that start with "[" (the dated and backfilled lines).
static unsigned CountLines(const char *text, unsigned len) {
    unsigned count = 0;
    for (unsigned i = 0; i < len; ++i)
        if ((i == 0 || text[i - 1] == '\n') && text[i] == '[') ++count;
    return count;
}

// The newest file's number (0 when there is none) and how many lines it holds.
static unsigned NewestFile(int slot, unsigned *lines) {
    char path[MAX_PATH + 64];
    unsigned newest = 0;
    *lines = 0;
    for (unsigned k = 1; k <= kMaxFiles; ++k) {
        if (!HistoryFile(slot, k, path, sizeof(path)) || !Exists(path)) break;
        newest = k;
    }
    unsigned got = 0;
    if (newest && HistoryFile(slot, newest, path, sizeof(path)) && ReadWhole(path, &got))
        *lines = CountLines(ReadBuffer, got);
    return newest;
}

// The first file, with its header, when the slot has none.
static void CreateLog(int slot) {
    char path[MAX_PATH + 64];
    unsigned lines = 0;
    if (NewestFile(slot, &lines) || !HistoryFile(slot, 1, path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    Header(t, slot);
    Append(path, Line, t.n);
}

// One line, appended to the newest file, or to a new numbered file when the newest is full.
static void History(int slot, const char *text, bool backfilled = false) {
    char path[MAX_PATH + 64];
    if (slot < 1) return;
    unsigned lines = 0;
    unsigned newest = NewestFile(slot, &lines);
    unsigned file = !newest ? 1 : lines >= kLinesPerFile ? newest + 1 : newest;
    if (!HistoryFile(slot, file, path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    if (!Exists(path)) Header(t, slot);
    if (backfilled) {
        t.S("[backfilled, no date] ");
    } else {
        SYSTEMTIME now;
        GetLocalTime(&now);
        t.S("[").U(now.wYear).S("-").Two(now.wMonth).S("-").Two(now.wDay).S(" ").Two(now.wHour).S(":")
            .Two(now.wMinute).S(":").Two(now.wSecond).S("] ");
    }
    t.S(text).NL();
    if (Append(path, Line, t.n)) ++VF1Logs_Status.lines;
}

// ---- remarriage: the spouse a person married before in the same generation, from this slot's own Family
// History (the save forgets a spouse who left or died before any child). Lines after the last eviction only.
static bool NameBefore(const char *&p, const char *stop, char *out) {   // a name ending at `stop`
    unsigned k = 0;
    while (*p && *p != '\r' && *p != '\n' && !StartsWith(p, stop)) {
        if (k < 27) out[k++] = *p;
        ++p;
    }
    out[k] = 0;
    if (!StartsWith(p, stop)) return false;
    p += Length(stop);
    return k > 0;
}

static void SkipPast(const char *&p, const char *mark) {
    while (*p && *p != '\r' && *p != '\n' && !StartsWith(p, mark)) ++p;
    if (StartsWith(p, mark)) p += Length(mark);
}

static bool EarlierSpouse(int slot, int gen, const char *head, char *earlier) {
    char path[MAX_PATH + 64];
    earlier[0] = 0;
    unsigned lines = 0, newest = NewestFile(slot, &lines);
    for (unsigned k = 1; k <= newest; ++k) {
        unsigned got = 0;
        if (!HistoryFile(slot, k, path, sizeof(path)) || !ReadWhole(path, &got)) continue;
        for (const char *p = ReadBuffer; *p;) {
            const char *body = p;
            if (*body == '[') {
                SkipPast(body, "] ");
                if (StartsWith(body, "Evicted: ")) earlier[0] = 0;
                const char *q = body;
                bool married = StartsWith(q, "Married: ") || StartsWith(q, "Remarried: ");
                if (married) {
                    SkipPast(q, ": ");
                    char a[28], b[28];
                    if (NameBefore(q, " (", a)) {
                        SkipPast(q, ") and ");
                        if (NameBefore(q, " (", b)) {
                            SkipPast(q, "), generation ");
                            int g = 0;
                            while (*q >= '0' && *q <= '9') g = g * 10 + (*q++ - '0');
                            if (g == gen && SameText(a, head, 28)) Copy(earlier, b, 28);
                            else if (g == gen && SameText(b, head, 28)) Copy(earlier, a, 28);
                        }
                    }
                }
            }
            while (*p && *p != '\n') ++p;
            if (*p) ++p;
        }
    }
    return earlier[0] != 0;
}

// ================================================================ wiping a slot (Start Over, a new family)
// Deletes everything in <save folder>\Virtual Families 1 Patcher\Save <slot>\ except a Backups folder in it.
static void DeleteTree(char *path, unsigned len, unsigned cap, bool top) {
    if (len + 4 >= cap) return;
    Copy(path + len, "\\*", 3);
    WIN32_FIND_DATAA found;
    HANDLE h = FindFirstFileA(path, &found);
    path[len] = 0;
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        const char *name = found.cFileName;
        if (name[0] == '.' && (name[1] == 0 || (name[1] == '.' && name[2] == 0))) continue;
        bool dir = (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
        if (top && dir && lstrcmpiA(name, "Backups") == 0) continue;
        unsigned n = Length(name);
        if (len + 1 + n + 1 >= cap) continue;
        path[len] = '\\';
        Copy(path + len + 1, name, n + 1);
        if (dir) {
            DeleteTree(path, len + 1 + n, cap, false);
            RemoveDirectoryA(path);
        } else {
            if (found.dwFileAttributes & FILE_ATTRIBUTE_READONLY) SetFileAttributesA(path, FILE_ATTRIBUTE_NORMAL);
            DeleteFileA(path);
        }
        path[len] = 0;
    } while (FindNextFileA(h, &found));
    FindClose(h);
}

static void WipeSlot(int slot) {
    char path[MAX_PATH + 64];
    Text t;
    t.Init(path, sizeof(path));
    if (!SlotRoot(slot, t)) return;
    DeleteTree(path, t.n, sizeof(path), true);
    ++VF1Logs_Status.wipes;
}

// ================================================================ the events
static int gInLoad;
static int gPendingEviction;      // vf1fun's Evict Family: the next new family is the same slot's next family

// ---- births: what the physiology pass delivered
struct PassState {
    int reserved[3];
    int pregnant[LOGS_HOUSEHOLD_SLOTS];
    unsigned char present[LOGS_HOUSEHOLD_SLOTS];
};
static PassState Before;

static void SnapshotPass(PassState &s) {
    const unsigned char *gs = GameState();
    for (int k = 0; k < 3; ++k) s.reserved[k] = gs ? I32(gs, LOGS_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) : -1;
    for (int i = 0; i < (int)LOGS_HOUSEHOLD_SLOTS; ++i) {
        const unsigned char *v = Villager(i);
        s.pregnant[i] = I32(v, LOGS_VILLAGER_PREGNANT);
        s.present[i] = v[LOGS_VILLAGER_PRESENT];
    }
}

// The father: the current generation's other parent whose head and body are the ones the game kept at
// conception (Impregnate stores the patriarch's head and body it is given at +0x2AD0 / +0x2ACC; the name it is
// given is the constant "Joey"). Empty when no parent matches.
static void Father(const Person &mother, char *out) {
    out[0] = 0;
    unsigned char *rec = Record(Generations());
    const unsigned char *m = Villager(mother.slot);
    if (!rec || !m) return;
    for (int k = 0; k < 2; ++k) {
        unsigned char *peep = Peep(rec, k);
        unsigned char *other = Peep(rec, 1 - k);
        if (!peep[LOGS_PEEP_VALID] || !SameText((const char *)peep, mother.name, 25) || !other[LOGS_PEEP_VALID]) continue;
        if (I32(other, LOGS_PEEP_HEAD) == I32(m, LOGS_VILLAGER_FATHER_HEAD) &&
            I32(other, LOGS_PEEP_BODY) == I32(m, LOGS_VILLAGER_FATHER_BODY)) {
            Copy(out, other, 25);
            out[25] = 0;
        }
        return;
    }
}

static void OnBirths(int mother) {
    int slot = CurrentSlot();
    const unsigned char *gs = GameState();
    if (!slot || !gs) return;
    int born[3], n = 0;
    for (int k = 0; k < 3; ++k) {
        int b = Before.reserved[k];
        if (b < 0 || b >= (int)LOGS_HOUSEHOLD_SLOTS || b == mother) continue;
        if (I32(gs, LOGS_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) != -1) continue;
        if (Before.present[b] || !Villager(b)[LOGS_VILLAGER_PRESENT]) continue;
        born[n++] = b;
    }
    if (!n) return;
    Person m;
    Capture(Villager(mother), m);
    char father[28];
    Father(m, father);
    Text h;
    h.Init(Body, sizeof(Body));
    h.S(n == 2 ? "Twins born to " : n == 3 ? "Triplets born to " : "Born to ").Name(m.name, LOGS_VILLAGER_NAME_LEN)
        .S(" and ");
    if (father[0]) h.Name(father, 25); else h.S("an unknown father");
    h.S(", generation ").I(Generations()).S(": ");
    for (int i = 0; i < n; ++i) {
        Person c;
        Capture(Villager(born[i]), c);
        if (i) h.S(i == n - 1 ? " and " : ", ");
        h.Name(c.name, LOGS_VILLAGER_NAME_LEN).S(" (").S(SexWord(c.sex)).S(")");
    }
    History(slot, Body);
}

// ---- deaths (each caller sets the villager's present byte to 0 right after, so each death is reported once)
static void ReportDeathHook(ReportDeathFn next, void *tree, void *villager) {
    const unsigned char *v = (const unsigned char *)villager;
    Person p;
    Capture(v, p);
    bool dead = v && I32(v, LOGS_VILLAGER_HEALTH) <= 0;
    int cause = v ? I32(v, LOGS_VILLAGER_CAUSE) : -1;
    int role = TreeRole(p);
    int gen = Generations();
    next(tree, villager);
    int slot = CurrentSlot();
    if (!dead || p.slot < 0 || !slot) return;
    Text h;
    h.Init(Body, sizeof(Body));
    h.S("Died: ");
    Who(h, p);
    h.S(", ").S(RoleWord(role)).S(", generation ").I(gen).S(": ").S(CauseWord(cause));
    History(slot, Body);
}

// ---- marriage and remarriage (UpdateParents: whichever of the two is not in the record yet marries in)
static void OnMarriage(const Person &head, const Person &spouse, int gen) {
    int slot = CurrentSlot();
    if (!slot) return;
    char earlier[28];
    bool again = EarlierSpouse(slot, gen, head.name, earlier);
    Text h;
    h.Init(Body, sizeof(Body));
    h.S(again ? "Remarried: " : "Married: ");
    Who(h, head);
    h.S(" and ");
    Who(h, spouse);
    h.S(", generation ").I(gen);
    if (again) h.S("; earlier spouse: ").Name(earlier, 25);
    History(slot, Body);
}

// ---- the e-mail and pop-up events, and what each did to the family
struct Member { unsigned char present, left; Person p; };
static Member Household[LOGS_HOUSEHOLD_SLOTS];

static void SnapshotHousehold(Member *h) {
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        const unsigned char *v = Villager(s);
        h[s].present = v[LOGS_VILLAGER_PRESENT];
        h[s].left = v[LOGS_VILLAGER_LEFT_HOME];
        Capture(v, h[s].p);
    }
}

static void OnEvent(bool email, const char *title) {
    int slot = CurrentSlot();
    if (!slot) return;
    Text h;
    h.Init(Body, sizeof(Body));
    h.S(email ? "E-mail: \"" : "Pop-up: \"").Name(title, 200).S("\"");
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        const unsigned char *v = Villager(s);
        Person now;
        Capture(v, now);
        if (!Household[s].present && v[LOGS_VILLAGER_PRESENT]) {
            int role = TreeRole(now);
            h.S("; ");
            Who(h, now);
            if (role >= 2) h.S(" joined the family as a child, generation ").I(Generations());
            else h.S(" joined the household");
        } else if (Household[s].present && !Household[s].left && v[LOGS_VILLAGER_LEFT_HOME]) {
            h.S("; ");
            Who(h, now);
            h.S(" left home");
        } else if (Household[s].present && !v[LOGS_VILLAGER_PRESENT]) {
            h.S("; ");
            Who(h, Household[s].p);
            h.S(" left the house");
        }
    }
    History(slot, Body);
}

// ---- vf1fun's own family changes (VF1Logs_Event)
enum { EV_DIVORCE = 1, EV_EVICT = 2, EV_SPAWN_CHILD = 3, EV_ADOPT_CHILD = 4 };

extern "C" __declspec(dllexport) void __cdecl VF1Logs_Event(int kind, int who, int parentA, int parentB) {
    if (!VF1Logs_Status.installed) return;
    int slot = CurrentSlot();
    if (!slot) return;
    Person p, a, b;
    Capture(Villager(who), p);
    Capture(Villager(parentA), a);
    Capture(Villager(parentB), b);
    Text h;
    h.Init(Body, sizeof(Body));
    if (kind == EV_DIVORCE && p.slot >= 0) {
        // Logged before the spouse leaves: the record still holds the generation's other parent.
        unsigned char *rec = Record(Generations());
        h.S("Divorced: ");
        Who(h, p);
        h.S(" left the family, divorced from ");
        if (rec && Peep(rec, 0)[LOGS_PEEP_VALID]) h.Name((const char *)Peep(rec, 0), 25); else h.S("(nobody)");
        h.S(", generation ").I(Generations()).S(" (Divorce Spouse)");
    } else if (kind == EV_EVICT) {
        h.S("Evicted:");
        bool any = false;
        for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
            unsigned char *v = Villager(s);
            if (!v[LOGS_VILLAGER_PRESENT] || v[LOGS_VILLAGER_LEFT_HOME] || I32(v, LOGS_VILLAGER_HEALTH) <= 0) continue;
            h.S(any ? ", " : " ").Name((const char *)(v + LOGS_VILLAGER_NAME), LOGS_VILLAGER_NAME_LEN);
            any = true;
        }
        if (!any) h.S(" (nobody)");
        h.S(" left the house (Evict Family); the next family's history follows");
        gPendingEviction = 1;
    } else if (kind == EV_SPAWN_CHILD && p.slot >= 0) {
        h.S("Joined: ");
        Who(h, p);
        h.S(" as a child of ").Name(a.name, LOGS_VILLAGER_NAME_LEN);
        if (b.slot >= 0 && b.slot != a.slot) h.S(" and ").Name(b.name, LOGS_VILLAGER_NAME_LEN);
        h.S(", generation ").I(Generations()).S(" (Spawn Child)");
    } else if (kind == EV_ADOPT_CHILD && p.slot >= 0) {
        h.S("Joined: ");
        Who(h, p);
        h.S(", adopted, generation ").I(Generations()).S(" (Adopt Outside Child)");
    } else {
        return;
    }
    History(slot, Body);
}

// ================================================================ an existing family's first log
// What the save's Family Tree holds, once, when the slot's log has no lines yet: each generation's couple,
// its children, and who the tree records as dead (a slot of -1). Nothing the tree does not hold (no dates,
// ages, causes, twins or earlier spouses).
static void Backfill(int slot) {
    int gens = Generations();
    for (int g = 1; g <= gens; ++g) {
        unsigned char *rec = Record(g);
        if (!rec) continue;
        unsigned char *p1 = Peep(rec, 0), *p2 = Peep(rec, 1);
        Text h;
        if (p1[LOGS_PEEP_VALID] && p2[LOGS_PEEP_VALID]) {
            h.Init(Body, sizeof(Body));
            h.S("Married: ").Name((const char *)p1, 25).S(" (").S(SexWord(I32(p1, LOGS_PEEP_GENDER))).S(") and ")
                .Name((const char *)p2, 25).S(" (").S(SexWord(I32(p2, LOGS_PEEP_GENDER))).S("), generation ").I(g);
            History(slot, Body, true);
        }
        int n = 2 + RecordChildren(rec);
        for (int k = 2; k < n; ++k) {
            unsigned char *kid = Peep(rec, k);
            if (!kid[LOGS_PEEP_VALID]) continue;
            h.Init(Body, sizeof(Body));
            h.S("Child: ").Name((const char *)kid, 25).S(" (").S(SexWord(I32(kid, LOGS_PEEP_GENDER))).S("), generation ")
                .I(g);
            History(slot, Body, true);
        }
        for (int k = 0; k < n; ++k) {
            unsigned char *peep = Peep(rec, k);
            if (!peep[LOGS_PEEP_VALID] || I32(peep, LOGS_PEEP_SLOT) != -1) continue;
            h.Init(Body, sizeof(Body));
            h.S("Died: ").Name((const char *)peep, 25).S(" (").S(SexWord(I32(peep, LOGS_PEEP_GENDER))).S("), ")
                .S(RoleWord(k)).S(", generation ").I(g);
            History(slot, Body, true);
        }
    }
}

static void OnLoaded(int slot) {
    if (Generations() <= 0) return;        // no family: the new family's adoption starts the log
    CreateLog(slot);
    VF1Logs_Status.lastLoad = 1;
    char path[MAX_PATH + 64];
    for (unsigned k = 1; HistoryFile(slot, k, path, sizeof(path)) && Exists(path); ++k) {
        unsigned got = 0;
        if (ReadWhole(path, &got) && CountLines(ReadBuffer, got)) return;   // never backfilled twice
    }
    Backfill(slot);
    VF1Logs_Status.lastLoad = 2;
}

// ================================================================ the hooks
static void __fastcall PhysiologyHook(void *manager, void *) {
    SnapshotPass(Before);
    NextPhysiology(manager);
    for (int i = 0; i < (int)LOGS_HOUSEHOLD_SLOTS; ++i)
        if (Before.pregnant[i] && !I32(Villager(i), LOGS_VILLAGER_PREGNANT)) OnBirths(i);
}

static void __fastcall DeathEndHook(void *tree, void *, void *villager) { ReportDeathHook(NextReportDeathEnd, tree, villager); }
static void __fastcall BodyRemovalHook(void *tree, void *, void *villager) { ReportDeathHook(NextReportDeathBody, tree, villager); }

static void __fastcall RestartHook(void *state, void *) {
    int slot = CurrentSlot();
    if (slot) WipeSlot(slot);
    gPendingEviction = 0;
    NextRestart(state);
}

static void __fastcall EventDialogHook(void *dialog, void *, void *parent, int updateParent) {
    const unsigned char *d = (const unsigned char *)dialog;
    void *event = *(void *const *)(d + LOGS_EVENT_DIALOG_EVENT);
    const char *shown = *(const char *const *)(d + LOGS_EVENT_DIALOG_TITLE);
    char title[256];
    Text t;
    t.Init(title, sizeof(title));
    t.Name(shown, sizeof(title) - 1);
    bool email = event && ((ThisBoolFn)(*(void ***)event)[LOGS_EVENT_VSLOT_EMAIL / 4])(event);
    SnapshotHousehold(Household);
    NextDoModal(dialog, parent, updateParent);
    OnEvent(email, title);
}

static bool __fastcall UpdateParentsHook(void *tree, void *, void *a, void *b) {
    Person pa, pb;
    Capture((const unsigned char *)a, pa);
    Capture((const unsigned char *)b, pb);
    bool ok = OrigUpdateParents(tree, a, b);
    unsigned char *rec = Record(Generations());
    if (ok && !gInLoad && rec) {
        // The one who married in is the one UpdateParents wrote into the record's second parent.
        unsigned char *spouse = Peep(rec, 1);
        bool bIn = I32(spouse, LOGS_PEEP_SLOT) == pb.slot && SameText((const char *)spouse, pb.name, 25);
        if (bIn) OnMarriage(pa, pb, Generations()); else OnMarriage(pb, pa, Generations());
    }
    return ok;
}

static bool __fastcall StartNextGenerationHook(void *tree, void *, void *villager, int peep) {
    int before = Generations();
    bool ok = OrigStartNextGeneration(tree, villager, peep);
    int slot = CurrentSlot();
    if (ok && !gInLoad && before == 0 && slot) {
        // A brand-new family in this slot (a new game, or after Start Over): the slot's folder is the new
        // family's alone. After Evict Family the slot keeps its history.
        if (gPendingEviction) gPendingEviction = 0;
        else WipeSlot(slot);
        CreateLog(slot);
    }
    return ok;
}

static bool __fastcall LoadHook(void *state, void *, int slot) {
    ++gInLoad;
    bool ok = NextLoad(state, slot);
    --gInLoad;
    if (ok && slot >= 1 && slot <= 5) OnLoaded(slot);
    return ok;
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

// A 5-byte jmp at a pin's start to code outside the executable: another companion hooked that entry.
static bool ForeignEntry(unsigned va) {
    return *(const unsigned char *)va == 0xE9 && !InExe(JumpTarget(va));
}

static bool PinsMatch() {
    if ((unsigned)GetModuleHandleW(0) != 0x400000u) return false;
    unsigned end = ImageEnd();
    for (unsigned i = 0; i < sizeof(LOGS_PINS) / sizeof(LOGS_PINS[0]); ++i) {
        const LogsPin &p = LOGS_PINS[i];
        if (p.va < 0x401000u || p.va + p.len > end) return false;
        const unsigned char *live = (const unsigned char *)p.va;
        unsigned from = ForeignEntry(p.va) ? 5u : 0u;
        for (unsigned k = from; k < p.len; ++k)
            if (!p.mask[k] && live[k] != p.bytes[k]) return false;
    }
    return true;
}

static const unsigned char *PinBytes(unsigned va) {
    for (unsigned i = 0; i < sizeof(LOGS_PINS) / sizeof(LOGS_PINS[0]); ++i)
        if (LOGS_PINS[i].va == va) return LOGS_PINS[i].bytes;
    return 0;
}

struct Write5 { unsigned va; unsigned char bytes[5]; unsigned char original[5]; };
static const unsigned kMaxWrites = 8;
struct Plan {
    Write5 writes[kMaxWrites];
    unsigned count;
    unsigned load;             // theGameState's Load slot: the value it holds now
};

__declspec(align(4096)) static unsigned char Trampolines[4096];
static unsigned TrampolineUsed;

static void *CallHandler(unsigned i) {
    switch (i) {
    case LOGS_CALL_PHYSIOLOGY: return (void *)&PhysiologyHook;
    case LOGS_CALL_DEATH_END: return (void *)&DeathEndHook;
    case LOGS_CALL_BODY_REMOVAL: return (void *)&BodyRemovalHook;
    case LOGS_CALL_RESTART: return (void *)&RestartHook;
    case LOGS_CALL_EVENT_DIALOG: return (void *)&EventDialogHook;
    }
    return 0;
}

static void SetCallNext(unsigned i, unsigned target) {
    switch (i) {
    case LOGS_CALL_PHYSIOLOGY: NextPhysiology = (ThisVoidFn)target; break;
    case LOGS_CALL_DEATH_END: NextReportDeathEnd = (ReportDeathFn)target; break;
    case LOGS_CALL_BODY_REMOVAL: NextReportDeathBody = (ReportDeathFn)target; break;
    case LOGS_CALL_RESTART: NextRestart = (ThisVoidFn)target; break;
    case LOGS_CALL_EVENT_DIALOG: NextDoModal = (DoModalFn)target; break;
    }
}

static void *EntryHandler(unsigned i) {
    switch (i) {
    case LOGS_ENTRY_FT_UPDATE_PARENTS: return (void *)&UpdateParentsHook;
    case LOGS_ENTRY_FT_START_NEXT_GEN: return (void *)&StartNextGenerationHook;
    }
    return 0;
}

static void SetEntryOriginal(unsigned i, void *t) {
    switch (i) {
    case LOGS_ENTRY_FT_UPDATE_PARENTS: OrigUpdateParents = (UpdateParentsFn)t; break;
    case LOGS_ENTRY_FT_START_NEXT_GEN: OrigStartNextGeneration = (StartNextGenerationFn)t; break;
    }
}

static bool AddWrite(Plan &plan, unsigned va, unsigned char op, void *target) {
    if (plan.count >= kMaxWrites) return false;
    Write5 &w = plan.writes[plan.count++];
    w.va = va;
    w.bytes[0] = op;
    *(int *)(w.bytes + 1) = (int)((unsigned)target - (va + 5));
    return true;
}

static bool PlanHooks(Plan &plan) {
    plan.count = 0;
    TrampolineUsed = 0;
    // Calls: each must reach the stock function, or a companion's wrapper of it (outside the executable).
    for (unsigned i = 0; i < sizeof(LOGS_CALL_HOOKS) / sizeof(LOGS_CALL_HOOKS[0]); ++i) {
        const LogsCallHook &h = LOGS_CALL_HOOKS[i];
        if (*(const unsigned char *)h.site != 0xE8) return false;
        unsigned now = JumpTarget(h.site);
        if (now != h.target && InExe(now)) return false;
        SetCallNext(i, now);
        if (!AddWrite(plan, h.site, 0xE8, CallHandler(i))) return false;
    }
    // Entries: stock (steal whole instructions) or another companion's jmp (chain to it).
    for (unsigned i = 0; i < sizeof(LOGS_ENTRY_HOOKS) / sizeof(LOGS_ENTRY_HOOKS[0]); ++i) {
        const LogsEntryHook &h = LOGS_ENTRY_HOOKS[i];
        const unsigned char *pin = PinBytes(h.va);
        const unsigned char *live = (const unsigned char *)h.va;
        if (!pin || h.steal < 5 || h.steal > 16 || TrampolineUsed + 32 > sizeof(Trampolines)) return false;
        unsigned char *t = Trampolines + TrampolineUsed;
        bool stock = true;
        for (unsigned k = 0; k < h.steal; ++k) if (live[k] != pin[k]) stock = false;
        if (stock) {
            Copy(t, live, h.steal);
            t[h.steal] = 0xE9;
            *(int *)(t + h.steal + 1) = (int)((h.va + h.steal) - ((unsigned)t + h.steal + 5));
        } else if (ForeignEntry(h.va)) {
            t[0] = 0xE9;
            *(int *)(t + 1) = (int)(JumpTarget(h.va) - ((unsigned)t + 5));
        } else {
            return false;
        }
        SetEntryOriginal(i, t);
        TrampolineUsed += 32;
        if (!AddWrite(plan, h.va, 0xE9, EntryHandler(i))) return false;
    }
    // theGameState's Load slot: the stock function, or a companion's handler.
    unsigned load = *(const unsigned *)LOGS_GS_VTABLE_LOAD;
    if (load != LOGS_GS_LOAD && InExe(load)) return false;
    plan.load = load;
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
    DWORD old = 0;
    if (!VirtualProtect(Trampolines, sizeof(Trampolines), PAGE_EXECUTE_READWRITE, &old)) return false;
    for (unsigned i = 0; i < plan.count; ++i) {
        Write5 &w = plan.writes[i];
        Copy(w.original, (const void *)w.va, 5);
        if (!WriteCode(w.va, w.bytes, 5)) {
            for (unsigned j = 0; j < i; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, 5);
            return false;
        }
        ++VF1Logs_Status.writes;
    }
    NextLoad = (GameStateSlotFn)plan.load;
    if (!WriteSlot(LOGS_GS_VTABLE_LOAD, (unsigned)&LoadHook)) {
        for (unsigned j = 0; j < plan.count; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, 5);
        return false;
    }
    ++VF1Logs_Status.writes;
    return true;
}

// The Fun Patcher's own settings file, [Patches] FamilyHistory=1 (vf1fun loads this DLL only then).
static bool SettingOn() {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 14 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"settings.ini";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    return GetPrivateProfileIntW(L"Patches", L"FamilyHistory", 0, path) == 1;
}

extern "C" __declspec(dllexport) int __cdecl VF1Logs_Startup() {
    static bool started = false;
    if (started) return (int)VF1Logs_Status.installed;
    started = true;
    DWORD n = GetModuleFileNameW(ThisModule, Folder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    unsigned cut = n;
    while (cut > 0 && Folder[cut - 1] != L'\\') --cut;
    if (!cut) return 0;
    Folder[cut] = 0;
    bool on = SettingOn();
    VF1Logs_Status.requested = on ? 1u : 0u;
    if (!on || !PinsMatch()) return 0;
    static Plan plan;
    if (!PlanHooks(plan)) return 0;
    VF1Logs_Status.resolved = 1;
    if (Apply(plan)) VF1Logs_Status.installed = 1;
    return (int)VF1Logs_Status.installed;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
