// vf1logs.dll -- the "Family History" log, the Virtual Families 1 Fun Patcher's companion for one feature.
// One feature, one DLL.
//
// Virtual Families 1 keeps no history (docs/vf1-save-format.md section 3: no marriage, birth or death date,
// no earlier spouse, no twins), and its Family Tree forgets a spouse who leaves or dies before any child.
// So this DLL writes every family event down as it happens, one line each, from the game's own memory, with the
// game's own words where it has them (the string table in the executable: "Male", "Female", "Nursing", the
// causes of death, "{name} is going to college!", "New Generation", every e-mail subject and pop-up title), in
// the same wording as the Virtual Families 2 patcher's Family History. Per save slot, beside the save:
//
//   <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\Family History\Family History <k>.txt
//
// Every file opens with "Family: <family name> (Save <N>)"; every line is "[YYYY-MM-DD HH:MM:SS] <event>", the
// conceptions, births, deaths and events numbered ("Birth 3: ..."). Nothing is ever rewritten; after 2000 lines
// the next line opens the next numbered file. A new family (the game's new-family adoption) and Start Over wipe
// that slot's folder, Backups excepted; an existing family whose log has no lines yet gets what its save's Family
// Tree holds, marked "[backfilled, no date]". The line formats are listed in docs/FAMILY_HISTORY.md and read by
// patcher/vf1_family_history.py.
//
// vf1fun.dll loads this DLL (while the FamilyHistory setting is on) at the end of its own start-up, after
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
    unsigned records;     // Family History records written this session
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
typedef bool (__thiscall *ImpregnateFn)(void *villager, int one, const char *father, int head, int body, int flag);
typedef void (__thiscall *ThisVoidFn)(void *self);
typedef void *(__thiscall *ThisPtrFn)(void *self);
typedef int (__thiscall *DatingMailFn)(void *scene, int which, int param);
typedef int (__cdecl *LetterMailFn)(void *scene);
typedef void (__thiscall *ReportDeathFn)(void *tree, void *villager);
typedef bool (__thiscall *UpdateParentsFn)(void *tree, void *a, void *b);
typedef bool (__thiscall *StartNextGenerationFn)(void *tree, void *villager, int peep);
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);
typedef void (__thiscall *DoModalFn)(void *dialog, void *parent, int updateParent);
typedef bool (__thiscall *ThisBoolFn)(void *self);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
typedef const char *(__thiscall *GetStringFn)(void *strings, int id);
typedef void *(__cdecl *SingletonFn)();

static ImpregnateFn NextImpregnate;
static ThisVoidFn NextPhysiology;
static DatingMailFn NextDatingMail;
static LetterMailFn NextLetterMail;
static ThisVoidFn OrigSetLeftHome;
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

static const char *RoleText(int role) {
    return role == 0 ? "Parent" : role == 1 ? "Parent (married in)" : role >= 2 ? "Child" : "(not in the Family Tree)";
}

// ---- the Virtual Villagers patcher's record lines ("  Label: value"), a family member as it writes a villager:
// the name, then (one step further in) the age, sex, head and body.
static void Field(Text &t, const char *indent, const char *label, const char *value) {
    t.S(indent).S(label).S(": ").S(value).NL();
}

static void Member(Text &t, const char *indent, const char *label, const Person &p, const char *ageLabel) {
    char deeper[12];
    Text d;
    d.Init(deeper, sizeof(deeper));
    d.S(indent).S("  ");
    t.S(indent).S(label).S(": ").Name(p.name, LOGS_VILLAGER_NAME_LEN).NL();
    if (ageLabel) t.S(deeper).S(ageLabel).S(": ").U(Years(p.age)).NL();
    t.S(deeper).S("Sex: ").S(SexWord(p.sex)).NL();
    t.S(deeper).S("Head: ").I(p.head).NL();
    t.S(deeper).S("Body: ").I(p.body).NL();
}

// A family member at the top of a record: "  Name: ..", "  <age label>: ..", "  Sex: ..", "  Head: ..", "  Body: ..".
static void Self(Text &t, const Person &p, const char *ageLabel) {
    t.S("  Name: ").Name(p.name, LOGS_VILLAGER_NAME_LEN).NL();
    t.S("  ").S(ageLabel).S(": ").U(Years(p.age)).NL();
    t.S("  Sex: ").S(SexWord(p.sex)).NL();
    t.S("  Head: ").I(p.head).NL();
    t.S("  Body: ").I(p.body).NL();
}

static void Generation(Text &t, int g) { t.S("  Generation: ").I(g).NL(); }

// ================================================================ the Family History files
static char ReadBuffer[0x100000];
static char Line[0x4000];
static char Body[0x4000];

static const unsigned kRecordsPerFile = 2000;
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

// The records of the text: their heading lines start with "[" (the dated and backfilled ones).
static unsigned CountRecords(const char *text, unsigned len) {
    unsigned count = 0;
    for (unsigned i = 0; i < len; ++i)
        if ((i == 0 || text[i - 1] == '\n') && text[i] == '[') ++count;
    return count;
}

// The newest file's number (0 when there is none) and how many records it holds.
static unsigned NewestFile(int slot, unsigned *records) {
    char path[MAX_PATH + 64];
    unsigned newest = 0;
    *records = 0;
    for (unsigned k = 1; k <= kMaxFiles; ++k) {
        if (!HistoryFile(slot, k, path, sizeof(path)) || !Exists(path)) break;
        newest = k;
    }
    unsigned got = 0;
    if (newest && HistoryFile(slot, newest, path, sizeof(path)) && ReadWhole(path, &got))
        *records = CountRecords(ReadBuffer, got);
    return newest;
}

// The first file, with its header, when the slot has none.
static void CreateLog(int slot) {
    char path[MAX_PATH + 64];
    unsigned records = 0;
    if (NewestFile(slot, &records) || !HistoryFile(slot, 1, path, sizeof(path))) return;
    Text t;
    t.Init(Line, sizeof(Line));
    Header(t, slot);
    Append(path, Line, t.n);
}

// The highest number of a record kind ("Birth" in "[...] Birth 12") in every file of the slot's log: the next
// record of that kind gets the number after it.
static unsigned NextNumber(int slot, const char *kind) {
    char path[MAX_PATH + 64];
    unsigned highest = 0, m = Length(kind);
    for (unsigned k = 1; k <= kMaxFiles && HistoryFile(slot, k, path, sizeof(path)) && Exists(path); ++k) {
        unsigned got = 0;
        if (!ReadWhole(path, &got)) continue;
        for (unsigned i = 0; i < got; ++i) {
            if ((i && ReadBuffer[i - 1] != '\n') || ReadBuffer[i] != '[') continue;
            unsigned j = i;
            while (j < got && ReadBuffer[j] != ']' && ReadBuffer[j] != '\n') ++j;
            j += 2;
            if (j + m + 1 > got || !StartsWith(ReadBuffer + j, kind) || ReadBuffer[j + m] != ' ') continue;
            unsigned v = 0;
            for (j += m + 1; j < got && ReadBuffer[j] >= '0' && ReadBuffer[j] <= '9' && v < 100000000u; ++j)
                v = v * 10 + (unsigned)(ReadBuffer[j] - '0');
            if (v > highest && (j >= got || ReadBuffer[j] == '\r' || ReadBuffer[j] == '\n')) highest = v;
        }
    }
    return highest + 1;
}

// One record: the heading "[YYYY-MM-DD HH:MM:SS] <kind> <n>" (numbered per kind, as the Virtual Villagers logs
// number theirs) and its "  Label: value" lines, then a blank line; appended to the newest file, or to a new
// numbered file when the newest holds 2000 records.
static void Write(int slot, const char *kind, const char *lines, bool backfilled = false) {
    char path[MAX_PATH + 64];
    if (slot < 1) return;
    unsigned number = NextNumber(slot, kind);
    unsigned records = 0;
    unsigned newest = NewestFile(slot, &records);
    unsigned file = !newest ? 1 : records >= kRecordsPerFile ? newest + 1 : newest;
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
    t.S(kind).S(" ").U(number).NL().S(lines).NL();
    if (Append(path, Line, t.n)) ++VF1Logs_Status.records;
}

// ---- remarriage: the spouse a person married before in the same generation and why they left ("died" or
// "divorced"), from this slot's own Family History (the save forgets a spouse who left or died before any
// child). Records after the last eviction only.
static bool Value(const char *p, const char *label, char *out, unsigned cap) {   // "  <label>: <value>"
    if (!StartsWith(p, label)) return false;
    p += Length(label);
    unsigned k = 0;
    while (*p && *p != '\r' && *p != '\n') { if (k + 1 < cap) out[k++] = *p; ++p; }
    out[k] = 0;
    return true;
}

static bool EarlierSpouse(int slot, int gen, const char *head, char *earlier, char *how) {
    char path[MAX_PATH + 64];
    earlier[0] = how[0] = 0;
    char kind[16], a[28], b[28], g[12];
    kind[0] = a[0] = b[0] = g[0] = 0;
    for (unsigned k = 1; k <= kMaxFiles && HistoryFile(slot, k, path, sizeof(path)) && Exists(path); ++k) {
        unsigned got = 0;
        if (!ReadWhole(path, &got)) continue;
        for (const char *p = ReadBuffer;; ) {
            bool heading = *p == '[' || *p == 0;
            if (heading && kind[0]) {                  // the record before ends: what it says
                int gn = 0;
                for (const char *q = g; *q >= '0' && *q <= '9'; ++q) gn = gn * 10 + (*q - '0');
                if ((SameText(kind, "Marriage", 16)) && gn == gen && (SameText(a, head, 28) || SameText(b, head, 28))) {
                    Copy(earlier, SameText(a, head, 28) ? b : a, 28);
                    how[0] = 0;
                } else if (SameText(kind, "Death", 16) && earlier[0] && SameText(a, earlier, 28)) {
                    Copy(how, "died", 5);
                } else if (SameText(kind, "Divorce", 16) && earlier[0] && SameText(b, earlier, 28)) {
                    Copy(how, "divorced", 9);
                } else if (SameText(kind, "Evict Family", 16)) {
                    earlier[0] = how[0] = 0;
                }
                kind[0] = a[0] = b[0] = g[0] = 0;
            }
            if (!*p) break;
            if (*p == '[') {
                const char *q = p;
                while (*q && *q != ']') ++q;
                if (*q) q += 2;
                unsigned n = 0;
                while (*q && *q != '\r' && *q != '\n' && !(*q == ' ' && q[1] >= '0' && q[1] <= '9') && n < 15) kind[n++] = *q++;
                kind[n] = 0;
            } else {
                Value(p, "  Family member: ", a, sizeof(a)) || Value(p, "  Name: ", a, sizeof(a)) ||
                    Value(p, "  Married: ", b, sizeof(b)) || Value(p, "  Divorced: ", b, sizeof(b)) ||
                    Value(p, "  Generation: ", g, sizeof(g));
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
static int gStartedOver;          // the menu's Start Over: the next new family's log says so
static int gBoardingSchool;       // vf1fun's Boarding School is sending this slot's villager away (+1)
static int gInEvent;              // a Random Event's dialog is open
static char gEventTitle[256];     // the newest Random Event's title, as the player saw it
static const char *gEventKind = "Popup Event";

// ---- conception: the try-for-a-baby step's one Impregnate call; the father is the patriarch whose head and
// body the step passes (0x48EB99..0x48EBA8). Kept per mother for her births this session.
struct Conceived { int valid; char mother[28]; Person father; };
static Conceived Fathers[LOGS_HOUSEHOLD_SLOTS];

static void OnConception(const unsigned char *mother, const unsigned char *father) {
    int slot = CurrentSlot();
    if (!slot) return;
    Person m, f;
    Capture(mother, m);
    Capture(father, f);
    if (m.slot >= 0) {
        Conceived &c = Fathers[m.slot];
        c.valid = father != 0;
        Copy(c.mother, m.name, 28);
        c.father = f;
    }
    Text t;
    t.Init(Body, sizeof(Body));
    Member(t, "  ", "Mother", m, "Age at conception");
    if (father) Member(t, "  ", "Father", f, "Age at conception");
    else Field(t, "  ", "Father", "(unknown)");
    t.S("  Babies ").S(Word(LOGS_STR_NURSING)).S(": ").I(I32(mother, LOGS_VILLAGER_CARRIED)).NL();
    Generation(t, Generations());
    Write(slot, "Conception", Body);
}

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

// The father: the one this session saw at the conception, else the current generation's other parent whose
// head and body are the ones the game kept at conception (Impregnate stores the patriarch's head and body it is
// given at +0x2AD0 / +0x2ACC; the name it is given is the constant "Joey"). False when neither is known.
static bool Father(const Person &mother, Person &out) {
    Zero(&out, sizeof(out));
    if (mother.slot >= 0 && Fathers[mother.slot].valid && SameText(Fathers[mother.slot].mother, mother.name, 28)) {
        out = Fathers[mother.slot].father;
        return true;
    }
    unsigned char *rec = Record(Generations());
    const unsigned char *m = Villager(mother.slot);
    if (!rec || !m) return false;
    for (int k = 0; k < 2; ++k) {
        unsigned char *peep = Peep(rec, k);
        unsigned char *other = Peep(rec, 1 - k);
        if (!peep[LOGS_PEEP_VALID] || !SameText((const char *)peep, mother.name, 25) || !other[LOGS_PEEP_VALID]) continue;
        if (I32(other, LOGS_PEEP_HEAD) != I32(m, LOGS_VILLAGER_FATHER_HEAD) ||
            I32(other, LOGS_PEEP_BODY) != I32(m, LOGS_VILLAGER_FATHER_BODY)) return false;
        Copy(out.name, other, 25);
        out.sex = I32(other, LOGS_PEEP_GENDER);
        out.head = I32(other, LOGS_PEEP_HEAD);
        out.body = I32(other, LOGS_PEEP_BODY);
        return true;
    }
    return false;
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
    Person m, f;
    Capture(Villager(mother), m);
    bool known = Father(m, f);
    if (m.slot >= 0) Fathers[m.slot].valid = 0;
    for (int i = 0; i < n; ++i) {
        Person c;
        Capture(Villager(born[i]), c);
        Text t;
        t.Init(Body, sizeof(Body));
        t.S("  Child: ").Name(c.name, 25).NL();
        t.S("    Sex: ").S(SexWord(c.sex)).NL().S("    Head: ").I(c.head).NL().S("    Body: ").I(c.body).NL();
        t.S("  Mother: ").Name(m.name, 25).NL().S("    Head: ").I(m.head).NL().S("    Body: ").I(m.body).NL();
        if (known) t.S("  Father: ").Name(f.name, 25).NL().S("    Head: ").I(f.head).NL().S("    Body: ").I(f.body).NL();
        else Field(t, "  ", "Father", "(unknown)");
        Field(t, "  ", "Born as", n == 1 ? "Single birth" : n == 2 ? "Twin" : "Triplet");
        Generation(t, Generations());
        Write(slot, "Birth", Body);
    }
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
    char widowed[28];
    widowed[0] = 0;
    if (dead && (role == 0 || role == 1)) {            // the other parent, alive, is left with no spouse
        unsigned char *rec = Record(gen);
        unsigned char *other = rec ? Peep(rec, 1 - role) : 0;
        if (other && other[LOGS_PEEP_VALID] && I32(other, LOGS_PEEP_SLOT) != -1) {
            Copy(widowed, other, 25);
            widowed[25] = 0;
        }
    }
    next(tree, villager);
    int slot = CurrentSlot();
    if (!dead || p.slot < 0 || !slot) return;
    Text t;
    t.Init(Body, sizeof(Body));
    t.S("  Name: ").Name(p.name, 25).NL();
    t.S("  Age at death: ").U(Years(p.age)).NL();
    t.S("  Sex: ").S(SexWord(p.sex)).NL();
    Field(t, "  ", "Cause of death", CauseWord(cause));
    t.S("  Head: ").I(p.head).NL().S("  Body: ").I(p.body).NL();
    Field(t, "  ", "Family role", RoleText(role));
    Generation(t, gen);
    if (widowed[0]) t.S("  Current spouse of ").Name(widowed, 25).S(": (none)").NL();
    Write(slot, "Death", Body);
}

// ---- marriage and remarriage (UpdateParents: the one it writes into the record's second parent married in)
static void OnMarriage(const Person &head, const Person &spouse, int gen) {
    int slot = CurrentSlot();
    if (!slot) return;
    char earlier[28], how[12];
    bool again = EarlierSpouse(slot, gen, head.name, earlier, how);
    Text t;
    t.Init(Body, sizeof(Body));
    Member(t, "  ", "Family member", head, "Age");
    Member(t, "  ", "Married", spouse, "Age");
    if (again) {
        t.S("  Remarried: yes").NL().S("  Earlier spouse: ").Name(earlier, 25);
        if (how[0]) t.S(" (").S(how).S(")");
        t.NL();
    }
    t.S("  Current spouse of ").Name(head.name, 25).S(": ").Name(spouse.name, 25).NL();
    Generation(t, gen);
    Write(slot, "Marriage", Body);
}

// ---- a generation begins: a new family, Next Generation (the heir chosen), Adopt New Person
static void OnGeneration(const unsigned char *v, int peep, int before) {
    int slot = CurrentSlot();
    if (!slot || !v) return;
    Person p;
    Capture(v, p);
    const char *how;
    if (before == 0) {
        if (gPendingEviction) {
            gPendingEviction = 0;
            how = "Founder (after the eviction)";
        } else {
            // A brand-new family in this slot (a new game, or after Start Over): the folder is the new family's.
            WipeSlot(slot);
            CreateLog(slot);
            if (gStartedOver) Write(slot, "Start Over", "  The earlier family's history was cleared.\r\n");
            how = "Founder (adopted and started the family)";
        }
        gStartedOver = 0;
    } else {
        how = peep < 0 ? "Adopt New Person" : "Heir (inherited the house)";
    }
    Text t;
    t.Init(Body, sizeof(Body));
    Self(t, p, "Age");
    Field(t, "  ", "How", how);
    Generation(t, Generations());
    Write(slot, before && peep >= 0 ? Word(LOGS_STR_NEW_GENERATION) : "Generation", Body);
}

// ---- leaving home: at 19 (the game's own picture caption, "{name} is going to college!"), The Talent Scout,
// the patcher's Boarding School
static void OnLeftHome(const unsigned char *v, unsigned from) {
    int slot = CurrentSlot();
    if (!slot || !v) return;
    Person p;
    Capture(v, p);
    Text t;
    t.Init(Body, sizeof(Body));
    Self(t, p, "Age");
    t.S("  What happened: ");
    if (from == LOGS_LEFT_HOME_AT_19) {
        for (const char *s = Word(LOGS_STR_COLLEGE_TITLE); *s;) {
            if (StartsWith(s, "{name}")) { t.Name(p.name, 25); s += 6; }
            else { char c[2] = { *s++, 0 }; t.S(c); }
        }
    } else if (from == LOGS_LEFT_HOME_TALENT_SCOUT) {
        t.S("Left home with ").Name(gInEvent ? gEventTitle : "The Talent Scout", 200).S(" (").S(gEventKind).S(")");
    } else if (gBoardingSchool == p.slot + 1) {
        t.S("Sent to Boarding School");
    } else {
        t.S("Left home");
    }
    t.NL();
    Generation(t, Generations());
    Write(slot, "Left Home", Body);
}

// ---- the Random Events (an Email Event or a Popup Event), and who joined or left the house with them
struct HouseMember { unsigned char present; Person p; };
static HouseMember Household[LOGS_HOUSEHOLD_SLOTS];

static void SnapshotHousehold(HouseMember *h) {
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        const unsigned char *v = Villager(s);
        h[s].present = v[LOGS_VILLAGER_PRESENT];
        Capture(v, h[s].p);
    }
}

// VV's "Arrived" record: a family member who joined the family from outside.
static void Arrived(int slot, const Person &c, const char *how, const Person *a, const Person *b) {
    Text t;
    t.Init(Body, sizeof(Body));
    Self(t, c, "Age at arrival");
    Field(t, "  ", "How", how);
    if (a) {
        t.S("  Parents:").NL();
        const Person *both[2] = { a, b };
        for (int k = 0; k < 2; ++k) {
            const Person *q = both[k];
            if (!q || q->slot < 0 || (k == 1 && b->slot == a->slot)) continue;
            t.S("    ").S(q->sex == 1 ? "Mother" : "Father").S(": ").Name(q->name, 25).NL();
            t.S("      Head: ").I(q->head).NL().S("      Body: ").I(q->body).NL();
        }
    }
    Field(t, "  ", "Family role", RoleText(TreeRole(c)));
    Generation(t, Generations());
    Write(slot, "Arrived", Body);
}

static void OnEvent() {
    int slot = CurrentSlot();
    if (!slot) return;
    char how[300];
    Text h;
    h.Init(how, sizeof(how));
    h.S("Adopted (").S(gEventKind).S(": ").Name(gEventTitle, 200).S(")");
    for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
        const unsigned char *v = Villager(s);
        if (!Household[s].present && v[LOGS_VILLAGER_PRESENT]) {
            Person now;
            Capture(v, now);
            Arrived(slot, now, how, 0, 0);
        } else if (Household[s].present && !v[LOGS_VILLAGER_PRESENT]) {
            Text t;
            t.Init(Body, sizeof(Body));
            Self(t, Household[s].p, "Age");
            t.S("  What happened: Left the house (").S(gEventKind).S(": ").Name(gEventTitle, 200).S(")").NL();
            Generation(t, Generations());
            Write(slot, "Left Home", Body);
        }
    }
}

static void EventRecord(int slot, const char *kind, const char *title, int choice) {
    Text t;
    t.Init(Body, sizeof(Body));
    t.S("  ").S(kind).S(": ").Name(title, 200).NL();
    if (choice >= 0) t.S("  Choice: ").S(choice ? "B" : "A").NL();
    Generation(t, Generations());
    Write(slot, "Random Event", Body);
}

// ---- vf1fun's own family changes (VF1Logs_Event)
enum { EV_DIVORCE = 1, EV_EVICT = 2, EV_SPAWN_CHILD = 3, EV_ADOPT_CHILD = 4, EV_ROLL_DICE = 5, EV_BOARDING_SCHOOL = 6 };

extern "C" __declspec(dllexport) void __cdecl VF1Logs_Event(int kind, int who, int a, int b) {
    if (!VF1Logs_Status.installed) return;
    int slot = CurrentSlot();
    if (!slot) return;
    Person p, pa, pb;
    Capture(Villager(who), p);
    Capture(Villager(a), pa);
    Capture(Villager(b), pb);
    Text t;
    t.Init(Body, sizeof(Body));
    if (kind == EV_DIVORCE && p.slot >= 0) {
        // Before the spouse leaves: the record still holds the generation's other parent.
        unsigned char *rec = Record(Generations());
        unsigned char *head = rec ? Peep(rec, 0) : 0;
        if (head && head[LOGS_PEEP_VALID]) {
            t.S("  Family member: ").Name((const char *)head, 25).NL();
            t.S("    Sex: ").S(SexWord(I32(head, LOGS_PEEP_GENDER))).NL();
            t.S("    Head: ").I(I32(head, LOGS_PEEP_HEAD)).NL().S("    Body: ").I(I32(head, LOGS_PEEP_BODY)).NL();
        } else {
            Field(t, "  ", "Family member", "(unknown)");
        }
        Member(t, "  ", "Divorced", p, "Age");
        Field(t, "  ", "How", "Divorce Spouse");
        if (head && head[LOGS_PEEP_VALID]) t.S("  Current spouse of ").Name((const char *)head, 25).S(": (none)").NL();
        Generation(t, Generations());
        Write(slot, "Divorce", Body);
    } else if (kind == EV_EVICT) {
        t.S("  Family members:");
        bool any = false;
        for (int s = 0; s < (int)LOGS_HOUSEHOLD_SLOTS; ++s) {
            unsigned char *v = Villager(s);
            if (!v[LOGS_VILLAGER_PRESENT] || I32(v, LOGS_VILLAGER_HEALTH) <= 0) continue;
            t.S(any ? ", " : " ").Name((const char *)(v + LOGS_VILLAGER_NAME), LOGS_VILLAGER_NAME_LEN);
            any = true;
        }
        if (!any) t.S(" (none)");
        t.NL();
        Generation(t, Generations());
        Write(slot, "Evict Family", Body);
        gPendingEviction = 1;
    } else if (kind == EV_SPAWN_CHILD && p.slot >= 0) {
        Arrived(slot, p, "Spawn Child", &pa, &pb);
    } else if (kind == EV_ADOPT_CHILD && p.slot >= 0) {
        Arrived(slot, p, "Adopted (Adopt Outside Child)", 0, 0);
    } else if (kind == EV_ROLL_DICE) {
        t.S("  Cost: $").I(a).NL();
        t.S("  ").S(gEventKind).S(": ").Name(gEventTitle[0] ? gEventTitle : "(none)", 200).NL();
        Generation(t, Generations());
        Write(slot, "Roll the Dice", Body);
    } else if (kind == EV_BOARDING_SCHOOL) {
        gBoardingSchool = who + 1;                   // SetLeftHome follows at once (villager_upgrades.inc)
    }
}

// ================================================================ an existing family's first log
// What the save's Family Tree holds, once, when the slot's log has no records yet: one record per generation, its
// parents, its children (a slot of -1: "Died: yes") and the newest generation's current spouse. Nothing the tree
// does not hold (no dates, ages, causes, twins or earlier spouses).
static void PeepLines(Text &t, const char *label, unsigned char *peep) {
    t.S("  ").S(label).S(": ").Name((const char *)peep, 25).NL();
    t.S("    Sex: ").S(SexWord(I32(peep, LOGS_PEEP_GENDER))).NL();
    t.S("    Head: ").I(I32(peep, LOGS_PEEP_HEAD)).NL().S("    Body: ").I(I32(peep, LOGS_PEEP_BODY)).NL();
    if (I32(peep, LOGS_PEEP_SLOT) == -1) t.S("    Died: yes").NL();
}

static void Backfill(int slot) {
    int gens = Generations();
    for (int g = 1; g <= gens; ++g) {
        unsigned char *rec = Record(g);
        if (!rec) continue;
        unsigned char *p1 = Peep(rec, 0), *p2 = Peep(rec, 1);
        bool v1 = p1[LOGS_PEEP_VALID] != 0, v2 = p2[LOGS_PEEP_VALID] != 0;
        Text t;
        t.Init(Body, sizeof(Body));
        if (v1) PeepLines(t, "Parent", p1);
        if (v2) PeepLines(t, "Parent (married in)", p2);
        int n = RecordChildren(rec);
        for (int c = 0; c < n; ++c)
            if (Peep(rec, 2 + c)[LOGS_PEEP_VALID]) PeepLines(t, "Child", Peep(rec, 2 + c));
        if (g == gens && v1 && v2 && I32(p1, LOGS_PEEP_SLOT) != -1 && I32(p2, LOGS_PEEP_SLOT) != -1)
            t.S("  Current spouse of ").Name((const char *)p1, 25).S(": ").Name((const char *)p2, 25).NL();
        Generation(t, g);
        t.S("  Note: Recorded afterwards (from the save's Family Tree: no dates, ages, causes, twins or earlier spouses)")
            .NL();
        Write(slot, "Family Tree", Body, true);
    }
}

static void OnLoaded(int slot) {
    if (Generations() <= 0) return;        // no family: the new family's adoption starts the log
    Zero(Fathers, sizeof(Fathers));
    CreateLog(slot);
    VF1Logs_Status.lastLoad = 1;
    char path[MAX_PATH + 64];
    for (unsigned k = 1; HistoryFile(slot, k, path, sizeof(path)) && Exists(path); ++k) {
        unsigned got = 0;
        if (ReadWhole(path, &got) && CountRecords(ReadBuffer, got)) return;   // never backfilled twice
    }
    Backfill(slot);
    VF1Logs_Status.lastLoad = 2;
}

// ================================================================ the hooks
static bool __fastcall ConceptionHook(void *mother, void *, int one, const char *father, int head, int body, int flag) {
    // The step passes the patriarch's head and body (0x48EB99..0x48EBB2): he is the father.
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
    gStartedOver = 1;
    NextRestart(state);
}

// A Random Event's dialog: an Email Event when the event is an e-mail (its vtable +0x14, as the chooser and the
// dialog's own draw ask it), else a Popup Event; its title as the dialog draws it (+0x54); after the player's
// choice (+0x830, 0 A / 1 B, on an event with choices), who joined or left the house with it.
static void __fastcall EventDialogHook(void *dialog, void *, void *parent, int updateParent) {
    const unsigned char *d = (const unsigned char *)dialog;
    void *event = *(void *const *)(d + LOGS_EVENT_DIALOG_EVENT);
    Text t;
    t.Init(gEventTitle, sizeof(gEventTitle));
    t.Name(*(const char *const *)(d + LOGS_EVENT_DIALOG_TITLE), sizeof(gEventTitle) - 1);
    bool email = event && ((ThisBoolFn)(*(void ***)event)[LOGS_EVENT_VSLOT_EMAIL / 4])(event);
    bool choices = event && ((ThisBoolFn)(*(void ***)event)[LOGS_EVENT_VSLOT_HAS_CHOICES / 4])(event);
    gEventKind = email ? "Email Event" : "Popup Event";
    SnapshotHousehold(Household);
    ++gInEvent;
    NextDoModal(dialog, parent, updateParent);
    --gInEvent;
    int slot = CurrentSlot();
    if (!slot || gInLoad) return;
    EventRecord(slot, gEventKind, gEventTitle, choices ? I32(d, LOGS_EVENT_DIALOG_CHOICE) : -1);
    OnEvent();
}

// The main scene opens a mail: type 2 is the dating e-mail (it opens the dating scene), type 3 a letter from a
// child who left home (the game composes it, no subject line).
static int __fastcall DatingMailHook(void *scene, void *, int which, int param) {
    int slot = CurrentSlot();
    if (slot && !gInLoad) EventRecord(slot, "Email Event", "A marriage proposal (the dating e-mail)", -1);
    return NextDatingMail(scene, which, param);
}

static int __cdecl LetterMailHook(void *scene) {
    int slot = CurrentSlot();
    if (slot && !gInLoad) EventRecord(slot, "Email Event", "A letter from a child who left home", -1);
    return NextLetterMail(scene);
}

static bool __fastcall UpdateParentsHook(void *tree, void *, void *a, void *b) {
    Person pa, pb;
    Capture((const unsigned char *)a, pa);
    Capture((const unsigned char *)b, pb);
    bool ok = OrigUpdateParents(tree, a, b);
    unsigned char *rec = Record(Generations());
    if (ok && !gInLoad && rec) {
        // The one who married in is the one UpdateParents wrote into the record's second parent; either sex.
        unsigned char *spouse = Peep(rec, 1);
        bool bIn = I32(spouse, LOGS_PEEP_SLOT) == pb.slot && SameText((const char *)spouse, pb.name, 25);
        if (bIn) OnMarriage(pa, pb, Generations()); else OnMarriage(pb, pa, Generations());
    }
    return ok;
}

static bool __fastcall StartNextGenerationHook(void *tree, void *, void *villager, int peep) {
    int before = Generations();
    bool ok = OrigStartNextGeneration(tree, villager, peep);
    if (ok && !gInLoad) OnGeneration((const unsigned char *)villager, peep, before);
    return ok;
}

static void __fastcall SetLeftHomeHook(void *villager, void *) {
    unsigned from = (unsigned)_ReturnAddress();
    bool was = ((unsigned char *)villager)[LOGS_VILLAGER_LEFT_HOME] != 0;
    OrigSetLeftHome(villager);
    if (!was && !gInLoad) OnLeftHome((const unsigned char *)villager, from);
    gBoardingSchool = 0;
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
static const unsigned kMaxWrites = 12;
struct Plan {
    Write5 writes[kMaxWrites];
    unsigned count;
    unsigned load;             // theGameState's Load slot: the value it holds now
};

__declspec(align(4096)) static unsigned char Trampolines[4096];
static unsigned TrampolineUsed;

static void *CallHandler(unsigned i) {
    switch (i) {
    case LOGS_CALL_CONCEPTION: return (void *)&ConceptionHook;
    case LOGS_CALL_PHYSIOLOGY: return (void *)&PhysiologyHook;
    case LOGS_CALL_DATING_MAIL: return (void *)&DatingMailHook;
    case LOGS_CALL_LETTER_MAIL: return (void *)&LetterMailHook;
    case LOGS_CALL_DEATH_END: return (void *)&DeathEndHook;
    case LOGS_CALL_BODY_REMOVAL: return (void *)&BodyRemovalHook;
    case LOGS_CALL_RESTART: return (void *)&RestartHook;
    case LOGS_CALL_EVENT_DIALOG: return (void *)&EventDialogHook;
    }
    return 0;
}

static void SetCallNext(unsigned i, unsigned target) {
    switch (i) {
    case LOGS_CALL_CONCEPTION: NextImpregnate = (ImpregnateFn)target; break;
    case LOGS_CALL_PHYSIOLOGY: NextPhysiology = (ThisVoidFn)target; break;
    case LOGS_CALL_DATING_MAIL: NextDatingMail = (DatingMailFn)target; break;
    case LOGS_CALL_LETTER_MAIL: NextLetterMail = (LetterMailFn)target; break;
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
    case LOGS_ENTRY_V_SET_LEFT_HOME: return (void *)&SetLeftHomeHook;
    }
    return 0;
}

static void SetEntryOriginal(unsigned i, void *t) {
    switch (i) {
    case LOGS_ENTRY_FT_UPDATE_PARENTS: OrigUpdateParents = (UpdateParentsFn)t; break;
    case LOGS_ENTRY_FT_START_NEXT_GEN: OrigStartNextGeneration = (StartNextGenerationFn)t; break;
    case LOGS_ENTRY_V_SET_LEFT_HOME: OrigSetLeftHome = (ThisVoidFn)t; break;
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
