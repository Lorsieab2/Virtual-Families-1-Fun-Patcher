// vf1logs.dll -- "Family Logs", the Virtual Families 1 Fun Patcher's companion for one feature: the Virtual
// Villagers Fun Patcher's logs, in the same format and folder layout, for a family. One feature, one DLL.
//
// Virtual Families 1 keeps no history (docs/vf1-save-format.md section 3: no life-event history, no
// marriage, birth or death date in a save), so every log is written by this DLL at the moment the event
// happens, from the game's own memory, with the game's own words where the game has them (the string
// table in the executable: "Male", "Female", "Nursing", the causes of death, "{name} is going to
// college!"). Per save slot, beside the save (the Virtual Villagers patcher's per-save layout):
//
//   <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\
//       Family History\Family History <k>.txt                                 every event, one line each
//       Births and Conceptions\Virtual Families 1 Births and Conceptions Log <k>.txt
//       Deaths\Virtual Families 1 Deaths Log <k>.txt                          with the cause
//       Events\Virtual Families 1 Events Log <k>.txt                          the patcher's own events
//       Family Population\Family Population - Save <N>.txt                    the household at each save
//       Family Statistics\Family Statistics - Save <N>.txt                    counts at each save
//   <save folder>\Virtual Families 1 Patcher\Save <N>\Data\
//       Parents\Virtual Families 1 Parents - Save <N>.dat                     every child's mother and father
//       Unaccounted Villagers\Virtual Families 1 Family Members at Last Save - Save <N>.dat
//       Family Statistics\Family Statistics - Save <N>.dat                    the counters behind the page
//       Log Checks\Virtual Families 1 Backfill - Save <N>.dat                 the once-only backfill marker
//
// Append-only logs are never rewritten; each rolls into a new numbered file (256 numbered records, or 2000
// history lines). A new family (the game's new-family adoption) and Start Over wipe that slot's folder,
// Backups excepted; an existing family seen for the first time gets its past generations from the save's
// Family Tree, marked "backfilled, no date", once.
//
// vf1fun.dll loads this DLL (while the FamilyLogs setting is on) at the end of its own start-up, after
// vf1kids.dll, and calls VF1Logs_Startup() once. Installing is: setting -> verify every pin (vf1logs_sites.h,
// proved by tools/vf1_logs_sites.py) -> plan -> apply, all or nothing. A function entry another companion
// already hooked (vf1kids.dll) is chained, never overwritten blindly. VF1 has no ASLR.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <intrin.h>

#include "vf1logs_sites.h"

#pragma intrinsic(_ReturnAddress)

struct LogsStatus {
    unsigned magic;
    unsigned version;
    unsigned requested;
    unsigned resolved;
    unsigned installed;
    unsigned writes;
    unsigned records;     // records and lines written this session
    unsigned lastLoad;    // 0 none, 1 logs created / found, 2 backfilled
    unsigned lastSave;    // 0 none, 1 snapshot written, 2 not written (no folder)
    unsigned wipes;       // slot folders wiped (Start Over, new family)
};
extern "C" __declspec(dllexport) volatile LogsStatus VF1Logs_Status = { 0x474C3156u, 1u, 0, 0, 0, 0, 0, 0, 0, 0 };

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
    Text &Name(const char *s, unsigned max) {   // a game name field: at most `max` bytes, tabs and line ends dropped
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
typedef bool (__thiscall *ImpregnateFn)(void *villager, int one, const char *father, int head, int body, int flag);
typedef void (__thiscall *ThisVoidFn)(void *self);
typedef void (__thiscall *ReportDeathFn)(void *tree, void *villager);
typedef bool (__thiscall *UpdateParentsFn)(void *tree, void *a, void *b);
typedef bool (__thiscall *AddOffspringFn)(void *tree, void *villager);
typedef bool (__thiscall *StartNextGenerationFn)(void *tree, void *villager, int peep);
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);
typedef void *(__thiscall *ThisPtrFn)(void *self);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
typedef const char *(__thiscall *GetStringFn)(void *strings, int id);
typedef void *(__cdecl *SingletonFn)();

static ImpregnateFn NextImpregnate;
static ThisVoidFn NextPhysiology;
static ReportDeathFn NextReportDeathEnd, NextReportDeathBody;
static ThisVoidFn NextRestart;
static UpdateParentsFn OrigUpdateParents;
static AddOffspringFn OrigAddOffspring;
static StartNextGenerationFn OrigStartNextGeneration;
static ThisVoidFn OrigSetLeftHome;
static GameStateSlotFn NextLoad, NextSave;

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
    int head;
    int body;
    char name[28];
};

static void Capture(const unsigned char *v, Person &p) {
    Zero(&p, sizeof(p));
    p.slot = SlotOf(v);
    if (!v) { p.slot = -1; return; }
    p.sex = I32(v, LOGS_VILLAGER_GENDER);
    p.age = I32(v, LOGS_VILLAGER_AGE);
    p.head = I32(v, LOGS_VILLAGER_HEAD);
    p.body = I32(v, LOGS_VILLAGER_BODY);
    Copy(p.name, v + LOGS_VILLAGER_NAME, LOGS_VILLAGER_NAME_LEN);
    p.name[LOGS_VILLAGER_NAME_LEN] = 0;
}

static unsigned Years(int units) { return units < 0 ? 0u : (unsigned)units / LOGS_UNITS_PER_YEAR; }

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

// ================================================================ files
static char ReadBuffer[0x100000];
static char Line[0x4000];
static char Body[0x4000];

enum { FILE_MISSING = 0, FILE_OK = 1, FILE_SHUT = -2 };

static int ReadWhole(const char *path, unsigned *got) {
    *got = 0;
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) {
        DWORD e = GetLastError();
        return e == ERROR_FILE_NOT_FOUND || e == ERROR_PATH_NOT_FOUND ? FILE_MISSING : FILE_SHUT;
    }
    DWORD n = 0;
    BOOL ok = ReadFile(h, ReadBuffer, sizeof(ReadBuffer) - 1, &n, 0);
    CloseHandle(h);
    if (!ok) return FILE_SHUT;
    ReadBuffer[n] = 0;
    *got = n;
    return FILE_OK;
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

static bool WriteAtomic(const char *path, const char *text, unsigned len) {
    char temp[MAX_PATH + 72];
    unsigned n = Length(path);
    if (n + 5 > sizeof(temp)) return false;
    MakeParents(path);
    Copy(temp, path, n);
    Copy(temp + n, ".tmp", 5);
    HANDLE h = CreateFileA(temp, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    BOOL ok = WriteFile(h, text, len, &written, 0) && written == len;
    if (ok) ok = FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok || !MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileA(temp);
        return false;
    }
    return true;
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

static bool LogFile(int slot, const char *sub, const char *stem, unsigned number, char *out, unsigned cap) {
    Text t;
    t.Init(out, cap);
    if (!SlotRoot(slot, t)) return false;
    t.S("\\Logs\\").S(sub).S("\\").S(stem);
    if (number) t.S(" ").U(number);
    t.S(".txt");
    return t.n + 8 < cap;
}

static bool SnapshotFile(int slot, const char *sub, const char *stem, char *out, unsigned cap) {
    Text t;
    t.Init(out, cap);
    if (!SlotRoot(slot, t)) return false;
    t.S("\\Logs\\").S(sub).S("\\").S(stem).S(" - Save ").U((unsigned)slot).S(".txt");
    return t.n + 8 < cap;
}

static bool DataFile(int slot, const char *kind, const char *stem, char *out, unsigned cap) {
    Text t;
    t.Init(out, cap);
    if (!SlotRoot(slot, t)) return false;
    t.S("\\Data\\").S(kind).S("\\").S(stem).S(" - Save ").U((unsigned)slot).S(".dat");
    return t.n + 8 < cap;
}

// "Family: <name> (Save <N>)" -- the header every log file opens with (the Virtual Villagers logs'
// "Village: <name> (Save <S>)").
static void Header(Text &t, int slot) {
    const char *name = FamilyName();
    t.S("Family: ");
    if (name[0]) t.Name(name, LOGS_GAME_STATE_FAMILY_NAME_LEN - 1); else t.S("(no name)");
    t.S(" (Save ").U((unsigned)slot).S(")").NL();
}

// ================================================================ the append-only logs
enum { LOG_HISTORY = 0, LOG_BIRTHS = 1, LOG_DEATHS = 2, LOG_EVENTS = 3, LOG_COUNT = 4 };
struct LogKind { const char *sub; const char *stem; const char *roll; unsigned per; };
static const LogKind kLogs[LOG_COUNT] = {
    { "Family History", "Family History", "[", 2000 },
    { "Births and Conceptions", "Virtual Families 1 Births and Conceptions Log", "Conception ", 256 },
    { "Deaths", "Virtual Families 1 Deaths Log", "Death ", 256 },
    { "Events", "Virtual Families 1 Events Log", "Event ", 256 },
};
static const unsigned kMaxLogFiles = 4096;

// Lines of the text that start with `marker`, and the highest number printed right after it.
static void CountMarkers(const char *text, unsigned len, const char *marker, unsigned *count, unsigned *highest) {
    unsigned m = Length(marker);
    for (unsigned i = 0; i < len; ++i) {
        if ((i == 0 || text[i - 1] == '\n') && i + m <= len && StartsWith(text + i, marker)) {
            ++*count;
            unsigned v = 0, j = i + m;
            while (j < len && text[j] >= '0' && text[j] <= '9' && v < 100000000u) v = v * 10 + (unsigned)(text[j++] - '0');
            if (v > *highest) *highest = v;
        }
    }
}

// The newest file of a log (0 when none), and the next number of `marker` after every file's highest.
static unsigned NewestFile(int slot, int kind, const char *marker, unsigned *next, unsigned *rolled) {
    char path[MAX_PATH + 64];
    unsigned newest = 0, highest = 0;
    *rolled = 0;
    for (unsigned k = 1; k <= kMaxLogFiles; ++k) {
        if (!LogFile(slot, kLogs[kind].sub, kLogs[kind].stem, k, path, sizeof(path)) || !Exists(path)) break;
        newest = k;
        if (marker) {
            unsigned got = 0, count = 0;
            if (ReadWhole(path, &got) == FILE_OK) CountMarkers(ReadBuffer, got, marker, &count, &highest);
        }
    }
    if (newest) {
        unsigned got = 0, count = 0, ignored = 0;
        if (LogFile(slot, kLogs[kind].sub, kLogs[kind].stem, newest, path, sizeof(path)) && ReadWhole(path, &got) == FILE_OK)
            CountMarkers(ReadBuffer, got, kLogs[kind].roll, &count, &ignored);
        *rolled = count;
    }
    if (next) *next = highest + 1;
    return newest;
}

// Appends one record (or history line) to the slot's log, rolling to a new numbered file when the newest
// one is full. `marker`: "Conception " etc. -- the record is numbered after the highest already printed in
// any of the log's files; 0: the text is written as it is. Returns the number given (or 1).
static unsigned WriteLog(int slot, int kind, const char *marker, const char *text) {
    char path[MAX_PATH + 64];
    unsigned next = 1, rolled = 0;
    unsigned newest = NewestFile(slot, kind, marker, &next, &rolled);
    unsigned file = newest ? newest : 1;
    if (newest && rolled >= kLogs[kind].per) file = newest + 1;
    if (!LogFile(slot, kLogs[kind].sub, kLogs[kind].stem, file, path, sizeof(path))) return 0;
    static char out[0x4400];
    Text t;
    t.Init(out, sizeof(out));
    if (!Exists(path)) Header(t, slot);
    if (marker) t.S(marker).U(next).NL();
    t.S(text);
    if (kind != LOG_HISTORY) t.NL();
    if (!Append(path, out, t.n)) return 0;
    ++VF1Logs_Status.records;
    return marker ? next : 1;
}

// The file of each log, created with its header if there is none yet (the owner: every log is there from
// the moment the family is).
static void CreateLogs(int slot) {
    char path[MAX_PATH + 64];
    for (int kind = 0; kind < LOG_COUNT; ++kind) {
        unsigned rolled = 0;
        if (NewestFile(slot, kind, 0, 0, &rolled)) continue;
        if (!LogFile(slot, kLogs[kind].sub, kLogs[kind].stem, 1, path, sizeof(path))) return;
        Text t;
        t.Init(Line, sizeof(Line));
        Header(t, slot);
        Append(path, Line, t.n);
    }
}

static void Stamp(Text &t, bool backfilled) {
    if (backfilled) { t.S("[backfilled, no date] "); return; }
    SYSTEMTIME now;
    GetLocalTime(&now);
    t.S("[").U(now.wYear).S("-").Two(now.wMonth).S("-").Two(now.wDay).S(" ").Two(now.wHour).S(":")
        .Two(now.wMinute).S(":").Two(now.wSecond).S("] ");
}

// One line of the Family History.
static void History(int slot, const char *text, bool backfilled = false) {
    if (slot < 1) return;
    Text t;
    t.Init(Line, sizeof(Line));
    Stamp(t, backfilled);
    t.S(text).NL();
    WriteLog(slot, LOG_HISTORY, 0, Line);
}

static void PersonLines(Text &t, const char *indent, const Person &p) {
    t.S(indent).S("Sex: ").S(SexWord(p.sex)).NL();
    t.S(indent).S("Head: ").I(p.head).NL();
    t.S(indent).S("Body: ").I(p.body).NL();
}

// ================================================================ the data files
// Every data file is text, versioned and tagged (first line), one tab-separated entry per line.

// ---- Parents: every child's mother and father, kept beyond the Family Tree (which holds one couple and
// six children per generation, and records neither parent on the child).
static void AddParents(int slot, const Person &child, const char *mother, const char *father, const char *how) {
    char path[MAX_PATH + 64];
    if (!DataFile(slot, "Parents", "Virtual Families 1 Parents", path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    if (!Exists(path)) t.S("VF1LOGS PARENTS 1").NL();
    t.S("child\t").I(child.slot).S("\t").Name(child.name, 25).S("\t").I(child.sex).S("\t").I(Generations()).S("\t")
        .Name(mother, 25).S("\t").Name(father, 25).S("\t").S(how).NL();
    Append(path, Line, t.n);
}

// The newest Parents entry of a child (slot, name and sex), its mother and father copied out.
static bool FindParents(int slot, const Person &child, char *mother, char *father) {
    char path[MAX_PATH + 64];
    unsigned got = 0;
    mother[0] = father[0] = 0;
    if (!DataFile(slot, "Parents", "Virtual Families 1 Parents", path, sizeof(path)) || ReadWhole(path, &got) != FILE_OK)
        return false;
    bool found = false;
    char *p = ReadBuffer, *end = ReadBuffer + got;
    while (p < end) {
        char *eol = p;
        while (eol < end && *eol != '\n') ++eol;
        char *field[8];
        unsigned nf = 0;
        char *f = p;
        for (char *q = p; q <= eol && nf < 8; ++q) {
            if (q == eol || *q == '\t' || *q == '\r') {
                field[nf++] = f;
                f = q + 1;
                if (q == eol || *q == '\r') break;
            }
        }
        if (nf == 8 && StartsWith(field[0], "child\t")) {
            Text s;
            char number[16];
            s.Init(number, sizeof(number));
            s.I(child.slot).S("\t");
            Text n;
            char name[40];
            n.Init(name, sizeof(name));
            n.Name(child.name, 25).S("\t");
            char sex[16];
            Text x;
            x.Init(sex, sizeof(sex));
            x.I(child.sex).S("\t");
            if (StartsWith(field[1], number) && StartsWith(field[2], name) && StartsWith(field[3], sex)) {
                unsigned k = 0;
                for (char *q = field[5]; *q != '\t' && k < 27; ++q) mother[k++] = *q;
                mother[k] = 0;
                k = 0;
                for (char *q = field[6]; *q != '\t' && k < 27; ++q) father[k++] = *q;
                father[k] = 0;
                found = true;
            }
        }
        p = eol + 1;
    }
    return found;
}

// ---- Deaths already logged, so each villager's death is logged once: in memory, and in the Family
// Members at Last Save file (a body is saved and its removal reports the death again after a load).
struct Logged { int valid; int sex; int age; char name[28]; };
static Logged DeathLogged[LOGS_HOUSEHOLD_SLOTS];

static bool WasLogged(const Person &p) {
    if (p.slot < 0) return false;
    const Logged &l = DeathLogged[p.slot];
    return l.valid && l.sex == p.sex && l.age == p.age && SameText(l.name, p.name, 25);
}

static void MarkLogged(const Person &p) {
    if (p.slot < 0) return;
    Logged &l = DeathLogged[p.slot];
    l.valid = 1;
    l.sex = p.sex;
    l.age = p.age;
    Copy(l.name, p.name, 28);
}

static void ClearSession() { Zero(DeathLogged, sizeof(DeathLogged)); }

static bool MembersFile(int slot, char *path, unsigned cap) {
    return DataFile(slot, "Unaccounted Villagers", "Virtual Families 1 Family Members at Last Save", path, cap);
}

static void WriteMembers(int slot) {
    char path[MAX_PATH + 64];
    if (!MembersFile(slot, path, sizeof(path))) return;
    static char out[0x8000];
    Text t;
    t.Init(out, sizeof(out));
    t.S("VF1LOGS MEMBERS 1").NL();
    t.S("family\t").Name(FamilyName(), LOGS_GAME_STATE_FAMILY_NAME_LEN - 1).NL();
    t.S("generations\t").I(Generations()).NL();
    unsigned count = 0;
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        unsigned char *v = Villager(s);
        Person p;
        Capture(v, p);
        if (!p.name[0]) continue;
        bool present = v[LOGS_VILLAGER_PRESENT] != 0;
        if (!present && !WasLogged(p)) continue;
        t.S("member\t").I(s).S("\t").Name(p.name, 25).S("\t").I(p.sex).S("\t").I(p.age).S("\t").I(p.head).S("\t")
            .I(p.body).S("\t").U(present ? 1u : 0u).S("\t").U(v[LOGS_VILLAGER_LEFT_HOME] ? 1u : 0u).S("\t")
            .I(I32(v, LOGS_VILLAGER_HEALTH)).S("\t").U(WasLogged(p) ? 1u : 0u).NL();
        ++count;
    }
    t.S("end\t").U(count).NL();
    WriteAtomic(path, out, t.n);
}

static int ParseInt(const char *&p) {
    bool neg = *p == '-';
    if (neg) ++p;
    int v = 0;
    while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    return neg ? -v : v;
}

// The deaths a previous session logged, from the slot's Family Members at Last Save file.
static void ReadMembers(int slot) {
    char path[MAX_PATH + 64];
    unsigned got = 0;
    ClearSession();
    if (!MembersFile(slot, path, sizeof(path)) || ReadWhole(path, &got) != FILE_OK) return;
    if (!StartsWith(ReadBuffer, "VF1LOGS MEMBERS 1")) return;
    const char *p = ReadBuffer;
    while (*p) {
        if (StartsWith(p, "member\t")) {
            p += 7;
            int s = ParseInt(p);
            if (*p == '\t') ++p;
            char name[28];
            unsigned k = 0;
            while (*p && *p != '\t' && *p != '\r' && *p != '\n') { if (k < 27) name[k++] = *p; ++p; }
            name[k] = 0;
            int values[7] = { 0 };
            for (int i = 0; i < 7 && *p == '\t'; ++i) { ++p; values[i] = ParseInt(p); }
            if (s >= 0 && s < (int)LOGS_HOUSEHOLD_SLOTS && values[6] == 1) {
                Logged &l = DeathLogged[s];
                l.valid = 1;
                l.sex = values[0];
                l.age = values[1];
                Copy(l.name, name, 28);
            }
        }
        while (*p && *p != '\n') ++p;
        if (*p) ++p;
    }
}

// ---- Family Statistics counters (babies born and deaths seen by the logs, from their baseline).
struct Counters { int babies; int deaths; };
static Counters gCounters;
static int gCountersSlot;

static bool CountersFile(int slot, char *path, unsigned cap) {
    return DataFile(slot, "Family Statistics", "Family Statistics", path, cap);
}

static void WriteCounters(int slot) {
    char path[MAX_PATH + 64];
    if (!CountersFile(slot, path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    t.S("VF1LOGS STATS 1").NL().S("babies\t").I(gCounters.babies).NL().S("deaths\t").I(gCounters.deaths).NL();
    WriteAtomic(path, Line, t.n);
}

static bool ReadCounters(int slot) {
    char path[MAX_PATH + 64];
    unsigned got = 0;
    gCounters.babies = gCounters.deaths = 0;
    gCountersSlot = slot;
    if (!CountersFile(slot, path, sizeof(path)) || ReadWhole(path, &got) != FILE_OK) return false;
    if (!StartsWith(ReadBuffer, "VF1LOGS STATS 1")) return false;
    const char *p = ReadBuffer;
    while (*p) {
        if (StartsWith(p, "babies\t")) { p += 7; gCounters.babies = ParseInt(p); }
        else if (StartsWith(p, "deaths\t")) { p += 7; gCounters.deaths = ParseInt(p); }
        while (*p && *p != '\n') ++p;
        if (*p) ++p;
    }
    return true;
}

static void Count(int slot, int babies, int deaths) {
    if (gCountersSlot != slot) ReadCounters(slot);
    gCounters.babies += babies;
    gCounters.deaths += deaths;
    WriteCounters(slot);
}

// ---- The backfill marker: an existing family's past is written once.
static bool BackfillFile(int slot, char *path, unsigned cap) {
    return DataFile(slot, "Log Checks", "Virtual Families 1 Backfill", path, cap);
}

static void WriteBackfillMarker(int slot, const char *how) {
    char path[MAX_PATH + 64];
    if (!BackfillFile(slot, path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    t.S("VF1LOGS BACKFILL 1").NL().S("family\t").Name(FamilyName(), LOGS_GAME_STATE_FAMILY_NAME_LEN - 1).NL()
        .S("how\t").S(how).NL();
    WriteAtomic(path, Line, t.n);
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
        if (top && dir && SameText(name, "Backups", 8)) continue;
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
    ClearSession();
    gCounters.babies = gCounters.deaths = 0;
    gCountersSlot = slot;
    ++VF1Logs_Status.wipes;
}

// ================================================================ the events
static int gInLoad;
static int gPendingEviction;      // vf1fun's Evict Family: the next new family is the same household's

static void PersonName(Text &t, const char *name) {
    if (name && name[0]) t.Name(name, 25); else t.S("(unknown)");
}

// ---- conception
static void OnConception(const unsigned char *mother, const unsigned char *father) {
    int slot = CurrentSlot();
    if (!slot) return;
    Person m, f;
    Capture(mother, m);
    Capture(father, f);
    const unsigned char *gs = GameState();
    int babies = I32(mother, LOGS_VILLAGER_CARRIED);
    Text t;
    t.Init(Body, sizeof(Body));
    t.S("  Mother: ").Name(m.name, 25).NL();
    t.S("    Age at conception: ").U(Years(m.age)).NL();
    PersonLines(t, "    ", m);
    t.S("  Father: ");
    PersonName(t, father ? f.name : 0);
    t.NL();
    if (father) {
        t.S("    Age at conception: ").U(Years(f.age)).NL();
        PersonLines(t, "    ", f);
    }
    t.S("  Babies ").S(Word(LOGS_STR_NURSING)).S(": ").I(babies).NL();
    t.S("  Generation: ").I(Generations()).NL();
    unsigned number = WriteLog(slot, LOG_BIRTHS, "Conception ", Body);
    for (int k = 0; gs && k < 3 && k < babies; ++k) {
        int b = I32(gs, LOGS_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k);
        Person baby;
        Capture(Villager(b), baby);
        if (baby.slot >= 0) AddParents(slot, baby, m.name, father ? f.name : "", "conceived");
    }
    Text h;
    h.Init(Body, sizeof(Body));
    h.S("Conception ").U(number).S(": ").Name(m.name, 25).S(" and ");
    PersonName(h, father ? f.name : 0);
    h.S(" (babies ").S(Word(LOGS_STR_NURSING)).S(": ").I(babies).S(")");
    History(slot, Body);
}

// ---- births: what the physiology pass delivered
struct PassState {
    int reserved[3];
    int pregnant[LOGS_HOUSEHOLD_SLOTS];
    int carried[LOGS_HOUSEHOLD_SLOTS];
    unsigned char present[LOGS_HOUSEHOLD_SLOTS];
};
static PassState Before;

static void SnapshotPass(PassState &s) {
    const unsigned char *gs = GameState();
    for (int k = 0; k < 3; ++k) s.reserved[k] = gs ? I32(gs, LOGS_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) : -1;
    for (int i = 0; i < (int)LOGS_HOUSEHOLD_SLOTS; ++i) {
        const unsigned char *v = Villager(i);
        s.pregnant[i] = I32(v, LOGS_VILLAGER_PREGNANT);
        s.carried[i] = I32(v, LOGS_VILLAGER_CARRIED);
        s.present[i] = v[LOGS_VILLAGER_PRESENT];
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
    const char *bornAs = n == 1 ? "Single birth" : n == 2 ? "Twins" : "Triplets";
    for (int i = 0; i < n; ++i) {
        Person c;
        Capture(Villager(born[i]), c);
        char motherName[28], fatherName[28];
        if (!FindParents(slot, c, motherName, fatherName)) {
            Copy(motherName, m.name, 28);
            fatherName[0] = 0;
        }
        Text t;
        t.Init(Body, sizeof(Body));
        t.S("  Child: ").Name(c.name, 25).NL();
        PersonLines(t, "    ", c);
        t.S("  Mother: ").Name(m.name, 25).NL();
        t.S("    Head: ").I(m.head).NL().S("    Body: ").I(m.body).NL();
        t.S("  Father: ");
        PersonName(t, fatherName);
        t.NL();
        t.S("  Born as: ").S(bornAs).NL();
        t.S("  Generation: ").I(Generations()).NL();
        unsigned number = WriteLog(slot, LOG_BIRTHS, "Birth ", Body);
        Text h;
        h.Init(Body, sizeof(Body));
        h.S("Birth ").U(number).S(": ").Name(c.name, 25).S(" (").S(SexWord(c.sex)).S(") was born to ").Name(m.name, 25)
            .S(" and ");
        PersonName(h, fatherName);
        if (n > 1) h.S(" (").S(bornAs).S(")");
        History(slot, Body);
    }
    Count(slot, n, 0);
}

// ---- deaths
static void OnDeath(const Person &p, int cause, int role, int gen) {
    int slot = CurrentSlot();
    if (!slot || WasLogged(p)) return;
    MarkLogged(p);
    const char *roleText = role == 0 ? "Parent" : role == 1 ? "Parent (married in)" : role >= 2 ? "Child" : "(not in the Family Tree)";
    Text t;
    t.Init(Body, sizeof(Body));
    t.S("  Name: ").Name(p.name, 25).NL();
    t.S("  Age at death: ").U(Years(p.age)).NL();
    t.S("  Sex: ").S(SexWord(p.sex)).NL();
    t.S("  Cause of death: ").S(CauseWord(cause)).NL();
    t.S("  Head: ").I(p.head).NL().S("  Body: ").I(p.body).NL();
    t.S("  Family role: ").S(roleText).NL();
    t.S("  Generation: ").I(gen).NL();
    unsigned number = WriteLog(slot, LOG_DEATHS, "Death ", Body);
    Text h;
    h.Init(Body, sizeof(Body));
    h.S("Death ").U(number).S(": ").Name(p.name, 25).S(" (").S(SexWord(p.sex)).S(", ").U(Years(p.age)).S(") died: ")
        .S(CauseWord(cause));
    History(slot, Body);
    Count(slot, 0, 1);
}

static void ReportDeathHook(ReportDeathFn next, void *tree, void *villager) {
    const unsigned char *v = (const unsigned char *)villager;
    Person p;
    Capture(v, p);
    bool dead = v && I32(v, LOGS_VILLAGER_HEALTH) <= 0;
    int cause = v ? I32(v, LOGS_VILLAGER_CAUSE) : -1;
    int role = TreeRole(p);
    int gen = Generations();
    next(tree, villager);
    if (dead && p.slot >= 0) OnDeath(p, cause, role, gen);
}

// ---- marriage
static void OnMarriage(const Person &a, const Person &b) {
    int slot = CurrentSlot();
    if (!slot) return;
    Text h;
    h.Init(Body, sizeof(Body));
    h.Name(a.name, 25).S(" (").S(SexWord(a.sex)).S(", ").U(Years(a.age)).S(") married ").Name(b.name, 25).S(" (")
        .S(SexWord(b.sex)).S(", ").U(Years(b.age)).S("), generation ").I(Generations());
    History(slot, Body);
}

// ---- a child who joins (not a baby: babies are added at conception and logged at birth)
static void OnJoined(const unsigned char *v) {
    int slot = CurrentSlot();
    if (!slot || !v) return;
    Person c;
    Capture(v, c);
    const char *p1 = (const char *)(v + LOGS_VILLAGER_BIO_PARENT1);
    const char *p2 = (const char *)(v + LOGS_VILLAGER_BIO_PARENT2);
    bool parents = p1[0] && p2[0];
    Text h;
    h.Init(Body, sizeof(Body));
    h.Name(c.name, 25).S(" (").S(SexWord(c.sex)).S(", ").U(Years(c.age)).S(") joined the family as a child");
    if (parents) h.S(" of ").Name(p1, 25).S(" and ").Name(p2, 25);
    else h.S(", adopted");
    h.S(", generation ").I(Generations());
    History(slot, Body);
    AddParents(slot, c, parents ? p2 : "", parents ? p1 : "", parents ? "joined" : "adopted");
}

// ---- a generation begins (a new family, Next Generation, Adopt New Person)
static void BackfillOrCreate(int slot);

static void OnGeneration(const unsigned char *v, int peep, int before) {
    int slot = CurrentSlot();
    if (!slot || !v) return;
    Person p;
    Capture(v, p);
    Text h;
    h.Init(Body, sizeof(Body));
    if (before == 0) {
        if (gPendingEviction) {
            gPendingEviction = 0;
            h.S("Generation 1 began after the eviction: ").Name(p.name, 25).S(" (").S(SexWord(p.sex)).S(", ")
                .U(Years(p.age)).S(") was adopted");
        } else {
            // A brand-new family in this slot (a new game, or after Start Over): the slot's folder is the new
            // family's alone.
            WipeSlot(slot);
            CreateLogs(slot);
            WriteBackfillMarker(slot, "new family");
            WriteCounters(slot);
            h.S("Generation 1 began: ").Name(p.name, 25).S(" (").S(SexWord(p.sex)).S(", ").U(Years(p.age))
                .S(") was adopted and started the family");
        }
    } else if (peep < 0) {
        h.S("Generation ").I(Generations()).S(" began: ").Name(p.name, 25).S(" (").S(SexWord(p.sex)).S(", ")
            .U(Years(p.age)).S(") was adopted (Adopt New Person)");
    } else {
        h.S(Word(LOGS_STR_NEW_GENERATION)).S(": generation ").I(Generations()).S(" began: ").Name(p.name, 25).S(" (")
            .S(SexWord(p.sex)).S(", ").U(Years(p.age)).S(") inherited the house");
    }
    History(slot, Body);
}

// ---- leaving home
static void OnLeftHome(const unsigned char *v) {
    int slot = CurrentSlot();
    if (!slot || !v) return;
    Person p;
    Capture(v, p);
    // The game's own picture caption: "{name} is going to college!"
    const char *title = Word(LOGS_STR_COLLEGE_TITLE);
    Text h;
    h.Init(Body, sizeof(Body));
    for (const char *s = title; *s;) {
        if (StartsWith(s, "{name}")) { h.Name(p.name, 25); s += 6; }
        else { char c[2] = { *s++, 0 }; h.S(c); }
    }
    h.S(" (").S(SexWord(p.sex)).S(", ").U(Years(p.age)).S(", left home)");
    History(slot, Body);
}

// ---- vf1fun's own events (VF1Logs_Event)
enum { EV_ROLL_DICE = 1, EV_DIVORCE = 2, EV_EVICT = 3, EV_ADOPT_NEW_PERSON = 4, EV_SPAWN_CHILD = 5,
       EV_ADOPT_CHILD = 6, EV_BOARDING_SCHOOL = 7 };

extern "C" __declspec(dllexport) void __cdecl VF1Logs_Event(int kind, int a, int b, int amount) {
    if (!VF1Logs_Status.installed) return;
    int slot = CurrentSlot();
    if (!slot) return;
    (void)b;
    Person p;
    Capture(Villager(a), p);
    bool who = p.slot >= 0 && p.name[0];
    const char *title = kind == EV_ROLL_DICE ? "Roll the Dice" : kind == EV_DIVORCE ? "Divorce Spouse"
        : kind == EV_EVICT ? "Evict Family" : kind == EV_ADOPT_NEW_PERSON ? "Adopt New Person"
        : kind == EV_SPAWN_CHILD ? "Spawn Child" : kind == EV_ADOPT_CHILD ? "Adopt Outside Child"
        : kind == EV_BOARDING_SCHOOL ? "Boarding School" : 0;
    if (!title) return;
    Text t;
    t.Init(Body, sizeof(Body));
    t.S("  Event: ").S(title).NL();
    if (kind == EV_ROLL_DICE) t.S("  Cost: $").I(amount).NL();
    if (who) {
        t.S("  Name: ").Name(p.name, 25).NL();
        t.S("  Age: ").U(Years(p.age)).NL();
        PersonLines(t, "  ", p);
    }
    if (kind == EV_EVICT) {
        t.S("  Family members:");
        bool any = false;
        for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
            unsigned char *v = Villager(s);
            if (!v[LOGS_VILLAGER_PRESENT] || I32(v, LOGS_VILLAGER_HEALTH) <= 0) continue;
            t.S(any ? ", " : " ").Name((const char *)(v + LOGS_VILLAGER_NAME), 25);
            any = true;
        }
        if (!any) t.S(" (none)");
        t.NL();
        gPendingEviction = 1;
    }
    t.S("  Generation: ").I(Generations()).NL();
    unsigned number = WriteLog(slot, LOG_EVENTS, "Event ", Body);
    Text h;
    h.Init(Body, sizeof(Body));
    h.S("Event ").U(number).S(": ").S(title);
    if (who) h.S(": ").Name(p.name, 25);
    if (kind == EV_ROLL_DICE) h.S(" ($").I(amount).S(")");
    History(slot, Body);
}

// ================================================================ save and load
static void WritePopulation(int slot) {
    char path[MAX_PATH + 64];
    if (!SnapshotFile(slot, "Family Population", "Family Population", path, sizeof(path))) return;
    static char out[0x10000];
    Text t;
    t.Init(out, sizeof(out));
    t.S("Virtual Families 1 Family Population").NL();
    Header(t, slot);
    t.S("Generation: ").I(Generations()).NL();
    unsigned k = 0;
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        unsigned char *v = Villager(s);
        if (!v[LOGS_VILLAGER_PRESENT]) continue;
        Person p;
        Capture(v, p);
        int role = TreeRole(p);
        t.NL().S("Family Member ").U(++k).NL();
        t.S("  Name: ").Name(p.name, 25).NL();
        t.S("  Age: ").U(Years(p.age)).NL();
        PersonLines(t, "  ", p);
        t.S("  Family role: ").S(role == 0 ? "Parent" : role == 1 ? "Parent (married in)" : role >= 2 ? "Child" : "(not in the Family Tree)").NL();
        int health = I32(v, LOGS_VILLAGER_HEALTH);
        t.S("  Health: ").I(health).NL();
        if (health <= 0) t.S("  Cause of death: ").S(CauseWord(I32(v, LOGS_VILLAGER_CAUSE))).NL();
        if (I32(v, LOGS_VILLAGER_PREGNANT)) {
            t.S("  ").S(Word(LOGS_STR_NURSING)).S(": yes").NL();
            t.S("  Babies ").S(Word(LOGS_STR_NURSING)).S(": ").I(I32(v, LOGS_VILLAGER_CARRIED)).NL();
        }
        if (v[LOGS_VILLAGER_LEFT_HOME]) t.S("  Left home: yes").NL();
    }
    if (!k) t.NL().S("(nobody)").NL();
    WriteAtomic(path, out, t.n);
}

static void WriteStatistics(int slot) {
    char path[MAX_PATH + 64];
    if (!SnapshotFile(slot, "Family Statistics", "Family Statistics", path, sizeof(path))) return;
    if (gCountersSlot != slot) ReadCounters(slot);
    unsigned members = 0;
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        unsigned char *v = Villager(s);
        if (v[LOGS_VILLAGER_PRESENT] && !v[LOGS_VILLAGER_LEFT_HOME] && I32(v, LOGS_VILLAGER_HEALTH) > 0) ++members;
    }
    float money = *(float *)LOGS_MONEY;
    unsigned dollars = money <= 0.f ? 0u : money >= 4294967040.f ? 4294967040u : (unsigned)money;
    Text t;
    t.Init(Line, sizeof(Line));
    t.S("Virtual Families 1").NL().S("Family Statistics").NL();
    Header(t, slot);
    t.NL();
    t.S("Generations: ").I(Generations()).NL();
    t.S("Family Members: ").U(members).NL();
    t.S("Babies Born: ").I(gCounters.babies).NL();
    t.S("Deaths: ").I(gCounters.deaths).NL();
    t.S("Oldest Family Member Ever: ").I(*(int *)LOGS_STATS_OLDEST).NL();
    t.S("Money: $").U(dollars).NL();
    t.S("Food: ").I(*(int *)LOGS_FOOD).NL();
    WriteAtomic(path, Line, t.n);
}

// An existing family seen for the first time: its past generations, from the save's Family Tree, once.
static void Backfill(int slot) {
    int gens = Generations();
    for (int g = 1; g <= gens; ++g) {
        unsigned char *rec = Record(g);
        if (!rec) continue;
        Text h;
        h.Init(Body, sizeof(Body));
        unsigned char *p1 = Peep(rec, 0), *p2 = Peep(rec, 1);
        h.S("Generation ").I(g).S(": ");
        if (p1[LOGS_PEEP_VALID]) h.Name((const char *)p1, 25).S(" (").S(SexWord(I32(p1, LOGS_PEEP_GENDER))).S(")");
        else h.S("(nobody)");
        if (p2[LOGS_PEEP_VALID]) h.S(" and ").Name((const char *)p2, 25).S(" (").S(SexWord(I32(p2, LOGS_PEEP_GENDER))).S(")");
        h.S(p2[LOGS_PEEP_VALID] ? " were the parents" : " was the parent");
        History(slot, Body, true);
        // The generation's couple, as the children's mother and father (by sex; a same-sex couple fills both
        // fields in the order the tree holds them).
        char mother[28], father[28];
        mother[0] = father[0] = 0;
        for (int k = 0; k < 2; ++k) {
            unsigned char *parent = Peep(rec, k);
            if (!parent[LOGS_PEEP_VALID]) continue;
            char *field = I32(parent, LOGS_PEEP_GENDER) == 1 ? (mother[0] ? father : mother) : (father[0] ? mother : father);
            Copy(field, parent, 25);
            field[25] = 0;
        }
        int n = RecordChildren(rec);
        for (int c = 0; c < n; ++c) {
            unsigned char *kid = Peep(rec, 2 + c);
            if (!kid[LOGS_PEEP_VALID]) continue;
            Text k;
            k.Init(Body, sizeof(Body));
            k.S("Generation ").I(g).S(": child ").Name((const char *)kid, 25).S(" (").S(SexWord(I32(kid, LOGS_PEEP_GENDER)))
                .S(")");
            if (I32(kid, LOGS_PEEP_SLOT) == -1) k.S(", died");
            History(slot, Body, true);
            Person child;
            Zero(&child, sizeof(child));
            child.slot = I32(kid, LOGS_PEEP_SLOT);
            child.sex = I32(kid, LOGS_PEEP_GENDER);
            Copy(child.name, kid, 25);
            child.name[25] = 0;
            AddParents(slot, child, mother, father, "backfilled");
        }
        if (I32(p1, LOGS_PEEP_SLOT) == -1 && p1[LOGS_PEEP_VALID]) {
            Text d;
            d.Init(Body, sizeof(Body));
            d.S("Generation ").I(g).S(": ").Name((const char *)p1, 25).S(" died");
            History(slot, Body, true);
        }
        if (I32(p2, LOGS_PEEP_SLOT) == -1 && p2[LOGS_PEEP_VALID]) {
            Text d;
            d.Init(Body, sizeof(Body));
            d.S("Generation ").I(g).S(": ").Name((const char *)p2, 25).S(" died");
            History(slot, Body, true);
        }
    }
    // The counters' baseline: the deaths the tree records (a slot of -1) and the babies the game counted, less
    // the ones not born yet.
    int deaths = 0;
    for (int g = 1; g <= gens; ++g) {
        unsigned char *rec = Record(g);
        if (!rec) continue;
        int n = 2 + RecordChildren(rec);
        for (int k = 0; k < n; ++k) {
            unsigned char *peep = Peep(rec, k);
            if (peep[LOGS_PEEP_VALID] && I32(peep, LOGS_PEEP_SLOT) == -1) ++deaths;
        }
    }
    int babies = *(int *)LOGS_STATS_BABIES;
    const unsigned char *gs = GameState();
    for (int k = 0; gs && k < 3; ++k) if (I32(gs, LOGS_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) != -1) --babies;
    gCounters.babies = babies < 0 ? 0 : babies;
    gCounters.deaths = deaths;
    gCountersSlot = slot;
    WriteCounters(slot);
}

static void BackfillOrCreate(int slot) {
    char path[MAX_PATH + 64];
    if (!BackfillFile(slot, path, sizeof(path))) return;
    bool marked = Exists(path);
    unsigned rolled = 0;
    bool history = NewestFile(slot, LOG_HISTORY, 0, 0, &rolled) != 0;
    CreateLogs(slot);
    VF1Logs_Status.lastLoad = 1;
    if (marked) return;
    if (history && rolled > 0) {           // logs already began here (an older marker was lost): never twice
        WriteBackfillMarker(slot, "logs found");
        return;
    }
    if (Generations() <= 0) return;        // no family yet: the new family's adoption starts the logs
    Backfill(slot);
    WriteBackfillMarker(slot, "backfilled");
    VF1Logs_Status.lastLoad = 2;
}

static void OnLoaded(int slot) {
    ReadMembers(slot);
    ReadCounters(slot);
    BackfillOrCreate(slot);
}

static void OnSaved(int slot) {
    char path[MAX_PATH + 64];
    if (!MembersFile(slot, path, sizeof(path))) { VF1Logs_Status.lastSave = 2; return; }
    WritePopulation(slot);
    WriteStatistics(slot);
    WriteMembers(slot);
    VF1Logs_Status.lastSave = 1;
}

// ================================================================ the hooks
static bool __fastcall ConceptionHook(void *mother, void *, int one, const char *father, int head, int body, int flag) {
    // The plan step passes the patriarch's head and body (0x48EB99..0x48EBB2): he is the father.
    unsigned char *patriarch = (unsigned char *)((ThisPtrFn)LOGS_VM_GET_PATRIARCH)(Manager());
    if (patriarch && (I32(patriarch, LOGS_VILLAGER_HEAD) != head || I32(patriarch, LOGS_VILLAGER_BODY) != body))
        patriarch = 0;
    bool ok = NextImpregnate(mother, one, father, head, body, flag);
    if (ok && !gInLoad) OnConception((const unsigned char *)mother, patriarch);
    return ok;
}

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

static bool __fastcall UpdateParentsHook(void *tree, void *, void *a, void *b) {
    Person pa, pb;
    Capture((const unsigned char *)a, pa);
    Capture((const unsigned char *)b, pb);
    bool ok = OrigUpdateParents(tree, a, b);
    if (!gInLoad) OnMarriage(pa, pb);
    return ok;
}

static bool __fastcall AddOffspringHook(void *tree, void *, void *villager) {
    unsigned from = (unsigned)_ReturnAddress();
    bool ok = OrigAddOffspring(tree, villager);
    if (ok && !gInLoad && !(from > LOGS_V_IMPREGNATE && from < LOGS_V_IMPREGNATE_END)) OnJoined((const unsigned char *)villager);
    return ok;
}

static bool __fastcall StartNextGenerationHook(void *tree, void *, void *villager, int peep) {
    int before = Generations();
    bool ok = OrigStartNextGeneration(tree, villager, peep);
    if (ok && !gInLoad) OnGeneration((const unsigned char *)villager, peep, before);
    return ok;
}

static void __fastcall SetLeftHomeHook(void *villager, void *) {
    bool was = ((unsigned char *)villager)[LOGS_VILLAGER_LEFT_HOME] != 0;
    OrigSetLeftHome(villager);
    if (!was && !gInLoad) OnLeftHome((const unsigned char *)villager);
}

static bool __fastcall LoadHook(void *state, void *, int slot) {
    ++gInLoad;
    bool ok = NextLoad(state, slot);
    --gInLoad;
    if (ok && slot >= 1 && slot <= 5) OnLoaded(slot);
    return ok;
}

static bool __fastcall SaveHook(void *state, void *, int slot) {
    bool ok = NextSave(state, slot);
    if (ok && slot >= 1 && slot <= 5) OnSaved(slot);
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

struct Write5 { unsigned va; unsigned char bytes[5]; unsigned char original[5]; unsigned len; };
static const unsigned kMaxWrites = 16;
struct Plan {
    Write5 writes[kMaxWrites];
    unsigned count;
    unsigned vtable[2];        // Load, Save: the values the slots hold now
};

__declspec(align(4096)) static unsigned char Trampolines[4096];
static unsigned TrampolineUsed;

static void *CallHandler(unsigned i) {
    switch (i) {
    case LOGS_CALL_CONCEPTION: return (void *)&ConceptionHook;
    case LOGS_CALL_PHYSIOLOGY: return (void *)&PhysiologyHook;
    case LOGS_CALL_DEATH_END: return (void *)&DeathEndHook;
    case LOGS_CALL_BODY_REMOVAL: return (void *)&BodyRemovalHook;
    case LOGS_CALL_RESTART: return (void *)&RestartHook;
    }
    return 0;
}

static void SetCallNext(unsigned i, unsigned target) {
    switch (i) {
    case LOGS_CALL_CONCEPTION: NextImpregnate = (ImpregnateFn)target; break;
    case LOGS_CALL_PHYSIOLOGY: NextPhysiology = (ThisVoidFn)target; break;
    case LOGS_CALL_DEATH_END: NextReportDeathEnd = (ReportDeathFn)target; break;
    case LOGS_CALL_BODY_REMOVAL: NextReportDeathBody = (ReportDeathFn)target; break;
    case LOGS_CALL_RESTART: NextRestart = (ThisVoidFn)target; break;
    }
}

static void *EntryHandler(unsigned i) {
    switch (i) {
    case LOGS_ENTRY_FT_UPDATE_PARENTS: return (void *)&UpdateParentsHook;
    case LOGS_ENTRY_FT_ADD_OFFSPRING: return (void *)&AddOffspringHook;
    case LOGS_ENTRY_FT_START_NEXT_GEN: return (void *)&StartNextGenerationHook;
    case LOGS_ENTRY_V_SET_LEFT_HOME: return (void *)&SetLeftHomeHook;
    }
    return 0;
}

static void SetEntryOriginal(unsigned i, void *t) {
    switch (i) {
    case LOGS_ENTRY_FT_UPDATE_PARENTS: OrigUpdateParents = (UpdateParentsFn)t; break;
    case LOGS_ENTRY_FT_ADD_OFFSPRING: OrigAddOffspring = (AddOffspringFn)t; break;
    case LOGS_ENTRY_FT_START_NEXT_GEN: OrigStartNextGeneration = (StartNextGenerationFn)t; break;
    case LOGS_ENTRY_V_SET_LEFT_HOME: OrigSetLeftHome = (ThisVoidFn)t; break;
    }
}

static bool AddWrite(Plan &plan, unsigned va, unsigned char op, void *target) {
    if (plan.count >= kMaxWrites) return false;
    Write5 &w = plan.writes[plan.count++];
    w.va = va;
    w.len = 5;
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
    // theGameState's Load and Save slots: the stock functions, or a companion's handlers.
    unsigned load = *(const unsigned *)LOGS_GS_VTABLE_LOAD, save = *(const unsigned *)LOGS_GS_VTABLE_SAVE;
    if ((load != LOGS_GS_LOAD && InExe(load)) || (save != LOGS_GS_SAVE && InExe(save))) return false;
    plan.vtable[0] = load;
    plan.vtable[1] = save;
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
    NextLoad = (GameStateSlotFn)plan.vtable[0];
    NextSave = (GameStateSlotFn)plan.vtable[1];
    if (!WriteSlot(LOGS_GS_VTABLE_LOAD, (unsigned)&LoadHook) || !WriteSlot(LOGS_GS_VTABLE_SAVE, (unsigned)&SaveHook)) {
        WriteSlot(LOGS_GS_VTABLE_LOAD, plan.vtable[0]);
        for (unsigned j = 0; j < plan.count; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, 5);
        return false;
    }
    VF1Logs_Status.writes += 2;
    return true;
}

// The Fun Patcher's own settings file, [Patches] FamilyLogs=1 (vf1fun loads this DLL only then).
static bool SettingOn() {
    wchar_t path[MAX_PATH];
    unsigned n = 0;
    while (Folder[n] && n + 14 < MAX_PATH) { path[n] = Folder[n]; ++n; }
    const wchar_t *name = L"settings.ini";
    for (unsigned i = 0; name[i]; ++i) path[n++] = name[i];
    path[n] = 0;
    return GetPrivateProfileIntW(L"Patches", L"FamilyLogs", 0, path) == 1;
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
    ClearSession();
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

#ifdef VF1LOGS_TEST
extern "C" __declspec(dllexport) void __cdecl VF1Logs_TestSetModule(unsigned module) { ThisModule = (HMODULE)module; }
extern "C" __declspec(dllexport) unsigned __cdecl VF1Logs_TestTrampoline(int entry) {
    return entry >= 0 && entry < 4 ? (unsigned)(Trampolines + 32 * (unsigned)entry) : 0u;
}
extern "C" __declspec(dllexport) int __cdecl VF1Logs_TestLogged(int slot) {
    return slot >= 0 && slot < (int)LOGS_HOUSEHOLD_SLOTS ? DeathLogged[slot].valid : -1;
}
#endif
