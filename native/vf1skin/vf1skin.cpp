// vf1skin.dll -- "Skin Tones", the Virtual Families 1 Fun Patcher's companion for one feature (one feature, one DLL).
// docs/SKIN_TONES.md is the whole design; tools/vf1_skin_sites.py proves every address used here.
//
// WHAT IT DOES (the owner's decisions, 2026-11-26). Every family member has a skin tone: one of ten, light to dark
// (Porcelain ... Ebony), or Game's own (the game's own skin). All bare skin is drawn in it -- the house (walking,
// actions, sitting), the portraits (Details, Adoption, the marriage proposal: the big heads and big bodies), the event
// pop-up's portrait, the Family Tree -- and the baby a mother carries is drawn in the baby's own tone.
//
// WHO GETS WHICH TONE. Founders, arrivals and everybody already in a family when the setting is first on get a random
// tone, from this DLL's own generator (never the game's rand(), so the game's own events never shift); with the
// patcher's Preferred skin tone (settings.ini [SkinTones] PreferredTone 1..10, the owner, 2026-11-28) about 4 in 5 of
// them get that tone instead. A baby's tone is
// rolled ONCE, when the game makes the baby's record (at the conception: CVillager::Impregnate spawns the babies at
// once): 95% the parents' average tone + rand(3) - 1, held to 1..10; 5% any tone (the Virtual Villagers patcher's
// rule, the game's own head rule on the tone number). A parent with no tone counts as the other parent's; twins and
// triplets copy the first baby. Nothing depends on sex. A copy the game makes of someone (the death behaviour's copy,
// Next Generation's adult heir) has their tone.
//
// THE FILE. The tones are never in the save. They live beside each save FILE, in the Up to 28 Children sidecar's layout
// (vf1kids.cpp), written right after theGameState::Save (temp file, then replace), rotated with the save (N -> N+20),
// naming the FNV-1a 64 hash and size of the save it was written with:
//
//   <save folder>\Virtual Families 1 Patcher Data\Skin Tones\<save file>.dat
//
// One entry per person, the Virtual Villagers patcher's two bytes (value: 0 none, 1..10 the tone, 15 Game's own chosen;
// birth: the tone they were born with or first given), keyed by the villager slot + sex + name (a rename follows the
// game's CFamilyTree::ChangeName), with up to two Family Tree places (generation, place), so the tree keeps drawing the
// dead and those who left in their tone. A file that does not validate is set aside (".unreadable-<k>.dat"), never
// overwritten or deleted; a file another program holds open is left exactly as it is (and nothing is toned or written
// for that save this session).
//
// HOW IT DRAWS. Each sheet of people is ONE picture the game keeps in memory for everybody; every draw of a cell ends in
// ldwGameWindowImpl::BlitRectWithAlpha 0x404C30. While a toned person is drawn, a blit from a sheet of people is given
// a kept copy of that ONE ROW of the sheet (one head, one outfit) with the skin recoloured (the Virtual Villagers
// patcher's method, number for number, patcher/vf1_skin_art.py: the tone's hue and chroma in OKLCh, the art's own
// shading kept as lightness offsets from the row's middle skin, never ashy), made the first time it is
// needed; the rectangle moves up to the copy's only row. At most 96 MB of copies are kept (least recently used go
// first). The game's own surfaces, its files, and every draw of someone with no tone are never touched.
//
// What is skin comes from a mask picture per sheet ("Skin Masks\<sheet>.png" beside this DLL: a 1-bit picture, white
// where the sheet has bare skin; it holds no game art). A mask is used only when the player's sheet file is the very
// file it was made from (size and FNV-1a 64, skin_masks.h) and the picture is that sheet's size; any other sheet is
// drawn as the game draws it.
//
// vf1fun.dll loads this DLL (while the SkinTones setting is on) after vf1kids, vf1logs and vf1revive, and calls
// VF1Skin_Startup() once: setting -> verify every pin -> plan -> apply, all or nothing. VF1 has no ASLR. Every buffer
// of code this DLL writes or runs is VirtualProtect-ed PAGE_EXECUTE_READWRITE.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "skin_masks.h"
#include "skin_tables.h"
#include "vf1skin_sites.h"

enum { TONE_NONE = 0, TONE_DEFAULT = 15 };

struct SkinStatus {
    unsigned magic, version;
    unsigned requested;  // the setting is on
    unsigned resolved;   // every pin matched and the plan was made
    unsigned installed;  // every hook is in
    unsigned entries;    // people held now
    unsigned sheets;     // sheets whose mask is in use
    unsigned refused;    // sheets whose file or mask did not match (drawn as the game draws them)
    unsigned rows;       // recoloured rows kept now
    unsigned bytes;      // their pixels' bytes
    unsigned swapped;    // blits given a recoloured row
    unsigned made;       // rows recoloured so far
    unsigned lastLoad;   // 0 none, 1 the save's own file, 2 the backup's, 3 another save of this family, 4 no file
                         // (everybody given a tone), 5 moved aside, 6 shut (left as it is), 7 damaged, not moved
    unsigned lastSave;   // 0 none, 1 written, 2 nothing to write, 3 write failed, 4 shut or not movable: nothing
    unsigned babies;     // babies given a tone this session
    unsigned preferred;  // the Preferred skin tone setting: 0 none, 1..10
};
extern "C" __declspec(dllexport) volatile SkinStatus VF1Skin_Status = { 0x4E4B5356u, 3u, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                                                         0, 0, 0, 0, 0 };

static HMODULE ThisModule;
static wchar_t Folder[MAX_PATH];      // this DLL's folder, with the closing backslash
static wchar_t GameFolder[MAX_PATH];  // the game's folder (the executable's), with the closing backslash

// ================================================================ small helpers
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

static bool NameEquals(const char *a, const char *b) {
    for (unsigned i = 0; i < SKIN_VILLAGER_NAME_LEN; ++i) {
        if (a[i] != b[i]) return false;
        if (!a[i]) return true;
    }
    return true;
}

static void CopyName(char *out, const char *name) {     // strncpy(out, name, 25) and a closing NUL
    unsigned i = 0;
    for (; i < SKIN_VILLAGER_NAME_LEN && name[i]; ++i) out[i] = name[i];
    for (; i <= SKIN_VILLAGER_NAME_LEN; ++i) out[i] = 0;
}

static int I32(const unsigned char *p, unsigned off) { return *(const int *)(p + off); }

static void Append(wchar_t *out, unsigned cap, const wchar_t *a, const wchar_t *b = 0, const wchar_t *c = 0) {
    unsigned n = 0;
    const wchar_t *parts[3] = { a, b, c };
    for (unsigned k = 0; k < 3; ++k)
        for (const wchar_t *p = parts[k]; p && *p && n + 1 < cap; ++p) out[n++] = *p;
    out[n] = 0;
}

// ---------------------------------------------------------------- the DLL's own log (vf1skin.log beside it)
static bool LogStarted;
static void Log(const char *fmt, unsigned a = 0) {
    wchar_t path[MAX_PATH];
    Append(path, MAX_PATH, Folder, L"vf1skin.log");
    char line[200];
    unsigned len = 0;
    for (const char *f = fmt; *f && len + 14 < sizeof(line); ++f) {
        if (f[0] == '%' && f[1] == 'u') {
            char d[12];
            unsigned k = 0, v = a;
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

// ================================================================ the game
static unsigned char *Manager() { return (unsigned char *)SKIN_VILLAGER_MANAGER; }
static unsigned char *Tree() { return (unsigned char *)SKIN_FAMILY_TREE; }
static unsigned char *GameState() { return *(unsigned char **)SKIN_GAME_STATE_INSTANCE; }

static unsigned char *Villager(int slot) {
    if (slot < 0 || slot >= (int)SKIN_HOUSEHOLD_SLOTS) return 0;
    return Manager() + SKIN_VILLAGER_ARRAY_OFFSET + (unsigned)slot * SKIN_VILLAGER_STRIDE;
}

static int SlotOf(const void *villager) {
    if (!villager) return -1;
    unsigned off = (unsigned)villager - (unsigned)(Manager() + SKIN_VILLAGER_ARRAY_OFFSET);
    if (off % SKIN_VILLAGER_STRIDE || off / SKIN_VILLAGER_STRIDE >= SKIN_HOUSEHOLD_SLOTS) return -1;
    return (int)(off / SKIN_VILLAGER_STRIDE);
}

static bool Reserved(int slot) {      // a baby not born yet holds its slot (its record is hidden until the birth)
    const unsigned char *gs = GameState();
    for (int k = 0; gs && k < 3; ++k)
        if (I32(gs, SKIN_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k) == slot) return true;
    return false;
}

static bool Exists(int slot) {
    const unsigned char *v = Villager(slot);
    return v && (v[SKIN_VILLAGER_PRESENT] || Reserved(slot)) && v[SKIN_VILLAGER_NAME] != 0;
}

static int Generations() {
    int g = I32(Tree(), 0);
    return g < 0 || g > (int)SKIN_TREE_GENERATIONS ? 0 : g;
}

static unsigned char *Record(int gen) {
    if (gen < 1 || gen > Generations()) return 0;
    return Tree() + (unsigned)gen * SKIN_FAMILY_RECORD_SIZE - SKIN_FAMILY_RECORD_BASE;
}

enum { PLACES = 2 + (int)SKIN_TREE_CHILDREN };      // 0 parent 1, 1 parent 2, 2..7 the six children
static unsigned char *Peep(unsigned char *rec, int place) {
    if (place == 0) return rec + SKIN_RECORD_PARENT1;
    if (place == 1) return rec + SKIN_RECORD_PARENT2;
    return rec + SKIN_RECORD_CHILDREN + (unsigned)(place - 2) * SKIN_PEEP_RECORD_SIZE;
}

static int PlaceCount(const unsigned char *rec) {
    int n = I32(rec, SKIN_RECORD_CHILD_COUNT);
    return 2 + (n < 0 ? 0 : n > (int)SKIN_TREE_CHILDREN ? (int)SKIN_TREE_CHILDREN : n);
}

// A tree entry's generation and place from its address (the tree is one static array).
static bool PlaceOf(const unsigned char *peep, int *gen, int *place) {
    unsigned off = (unsigned)peep - (unsigned)Tree();
    if ((unsigned)peep < (unsigned)Tree() || off < SKIN_RECORD_PARENT1) return false;
    int g = (int)((off + SKIN_FAMILY_RECORD_BASE) / SKIN_FAMILY_RECORD_SIZE);
    if (g < 1 || g > (int)SKIN_TREE_GENERATIONS) return false;
    unsigned in = off + SKIN_FAMILY_RECORD_BASE - (unsigned)g * SKIN_FAMILY_RECORD_SIZE;
    int p = -1;
    if (in == SKIN_RECORD_PARENT1) p = 0;
    else if (in == SKIN_RECORD_PARENT2) p = 1;
    else if (in >= SKIN_RECORD_CHILDREN && (in - SKIN_RECORD_CHILDREN) % SKIN_PEEP_RECORD_SIZE == 0
             && (in - SKIN_RECORD_CHILDREN) / SKIN_PEEP_RECORD_SIZE < SKIN_TREE_CHILDREN)
        p = 2 + (int)((in - SKIN_RECORD_CHILDREN) / SKIN_PEEP_RECORD_SIZE);
    if (p < 0) return false;
    *gen = g;
    *place = p;
    return true;
}

// ================================================================ the DLL's own random numbers
static unsigned RandomState;
static void Seed() {
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    RandomState = c.LowPart ^ (c.HighPart * 0x9E3779B9u) ^ GetTickCount() ^ (GetCurrentProcessId() << 16);
    if (!RandomState) RandomState = 0x2545F491u;
}
static unsigned Random(unsigned n) {        // xorshift32, 0..n-1
    unsigned x = RandomState;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    RandomState = x;
    return (unsigned)(((unsigned long long)x * n) >> 32);
}

// The patcher's "Preferred skin tone" (settings.ini [SkinTones] PreferredTone, the owner, 2026-11-28): 0 no preference,
// else 1..10. With one, about 4 in 5 randomly made family members get it and the rest a random tone; babies always
// inherit (Inherit, below), whatever the preference.
static int PreferredTone;
enum { PREFERRED_IN = 4, PREFERRED_OF = 5 };

static int RandomTone() {
    if (PreferredTone >= 1 && PreferredTone <= SKIN_TONE_COUNT && Random(PREFERRED_OF) < PREFERRED_IN)
        return PreferredTone;
    return (int)Random(SKIN_TONE_COUNT) + 1;
}

// The Virtual Villagers patcher's rule (skin_tone_rules.h vvfp_skin_tone_inherit): `father`, `mother` 1..10, anything
// else for not known.
static int Inherit(int father, int mother) {
    if (father < 1 || father > SKIN_TONE_COUNT) father = 0;
    if (mother < 1 || mother > SKIN_TONE_COUNT) mother = 0;
    unsigned r100 = Random(100), r3 = Random(3), rn = Random(SKIN_TONE_COUNT);
    if (r100 < 5 || (!father && !mother)) return (int)rn + 1;
    if (!father) father = mother;
    if (!mother) mother = father;
    int tone = (father + mother) / 2 + (int)r3 - 1;
    return tone < 1 ? 1 : tone > SKIN_TONE_COUNT ? SKIN_TONE_COUNT : tone;
}

// ================================================================ the people
// One entry, exactly as the file holds it (patcher/vf1_skin_tones.py ENTRY is the same table).
struct Entry {
    int slot;              // the villager slot while they are in the house, else -1
    int gender;            // 0 male, 1 female
    char name[26];         // the stored name (25 bytes) and a NUL
    unsigned char tone;    // 0 none, 1..10, 15 Game's own chosen
    unsigned char birth;   // the tone they were born with or first given (0 none)
    int head, body;        // as last seen
    int gen[2], place[2];  // their Family Tree places (generation 0: none)
    unsigned person;       // the same person (a copy the game made of them shares it)
};
enum { kEntry = 64, kMaxEntries = 400 };
typedef char EntrySizeCheck[sizeof(Entry) == kEntry ? 1 : -1];

static Entry Entries[kMaxEntries];
static unsigned EntryCount;
static unsigned NextPerson = 1;
static int SlotEntry[SKIN_HOUSEHOLD_SLOTS];       // index + 1 into Entries of each slot's person, 0 for none
static bool Suspended;                            // the save's file is shut: nothing toned, nothing written

static void ClearEntries() {
    EntryCount = 0;
    for (unsigned s = 0; s < SKIN_HOUSEHOLD_SLOTS; ++s) SlotEntry[s] = 0;
    VF1Skin_Status.entries = 0;
}

static bool IsVillager(const Entry &e, const unsigned char *v) {
    return e.gender == I32(v, SKIN_VILLAGER_GENDER) && NameEquals(e.name, (const char *)(v + SKIN_VILLAGER_NAME));
}

static bool IsPeep(const Entry &e, const unsigned char *peep) {
    return peep[SKIN_PEEP_VALID] && e.gender == I32(peep, SKIN_PEEP_GENDER) && NameEquals(e.name, (const char *)peep);
}

static bool HasPlace(const Entry &e, int gen, int place) {
    return (e.gen[0] == gen && e.place[0] == place) || (e.gen[1] == gen && e.place[1] == place);
}

static void AddPlace(Entry &e, int gen, int place) {
    if (HasPlace(e, gen, place)) return;
    int k = e.gen[0] == 0 ? 0 : 1;
    e.gen[k] = gen;
    e.place[k] = place;
}

static Entry *SlotPerson(int slot) {
    const unsigned char *v = Villager(slot);
    if (!v) return 0;
    int i = SlotEntry[slot] - 1;
    if (i >= 0 && (unsigned)i < EntryCount && Entries[i].slot == slot && IsVillager(Entries[i], v)) return &Entries[i];
    SlotEntry[slot] = 0;
    for (unsigned k = 0; k < EntryCount; ++k)
        if (Entries[k].slot == slot && IsVillager(Entries[k], v)) {
            SlotEntry[slot] = (int)k + 1;
            return &Entries[k];
        }
    return 0;
}

static void Reindex() {
    for (unsigned s = 0; s < SKIN_HOUSEHOLD_SLOTS; ++s) SlotEntry[s] = 0;
    VF1Skin_Status.entries = EntryCount;
}

static void Remove(unsigned i) {
    for (unsigned k = i; k + 1 < EntryCount; ++k) Entries[k] = Entries[k + 1];
    --EntryCount;
    Reindex();
}

// Room for one more: the first one with no slot and no tree place goes, else the first with no slot.
static Entry *NewEntry() {
    if (EntryCount >= kMaxEntries) {
        unsigned drop = kMaxEntries;
        for (unsigned i = 0; i < EntryCount && drop == kMaxEntries; ++i)
            if (Entries[i].slot < 0 && !Entries[i].gen[0] && !Entries[i].gen[1]) drop = i;
        for (unsigned i = 0; i < EntryCount && drop == kMaxEntries; ++i)
            if (Entries[i].slot < 0) drop = i;
        if (drop == kMaxEntries) return 0;
        Remove(drop);
    }
    Entry &e = Entries[EntryCount++];
    Zero(&e, sizeof e);
    e.slot = -1;
    VF1Skin_Status.entries = EntryCount;
    return &e;
}

// Whoever held this slot before is not in it any more (their tree places keep them).
static void Detach(int slot) {
    for (unsigned k = 0; k < EntryCount; ++k)
        if (Entries[k].slot == slot) Entries[k].slot = -1;
    if (slot >= 0 && slot < (int)SKIN_HOUSEHOLD_SLOTS) SlotEntry[slot] = 0;
}

static Entry *Bind(int slot, int tone, int birth, unsigned person) {
    const unsigned char *v = Villager(slot);
    Detach(slot);
    Entry *e = NewEntry();
    if (!e) return 0;
    e->slot = slot;
    e->gender = I32(v, SKIN_VILLAGER_GENDER);
    CopyName(e->name, (const char *)(v + SKIN_VILLAGER_NAME));
    e->head = I32(v, SKIN_VILLAGER_HEAD);
    e->body = I32(v, SKIN_VILLAGER_BODY);
    e->tone = (unsigned char)tone;
    e->birth = (unsigned char)birth;
    e->person = person ? person : NextPerson++;
    SlotEntry[slot] = (int)(e - Entries) + 1;
    return e;
}

static int NumericTone(const Entry *e) { return e && e->tone >= 1 && e->tone <= SKIN_TONE_COUNT ? e->tone : 0; }

// The current generation's two parents, when a new villager's own parents are exactly them (vf1fun's Spawn Child):
// their tones; otherwise 0.
static bool CoupleTones(const unsigned char *v, int *a, int *b) {
    unsigned char *rec = Record(Generations());
    if (!rec) return false;
    const char *p1 = (const char *)(v + SKIN_VILLAGER_PARENT1_NAME), *p2 = (const char *)(v + SKIN_VILLAGER_PARENT2_NAME);
    unsigned char *t1 = Peep(rec, 0), *t2 = Peep(rec, 1);
    if (!p1[0] || !p2[0] || !t1[SKIN_PEEP_VALID] || !t2[SKIN_PEEP_VALID]) return false;
    bool same = (NameEquals(p1, (const char *)t1) && NameEquals(p2, (const char *)t2))
             || (NameEquals(p1, (const char *)t2) && NameEquals(p2, (const char *)t1));
    if (!same) return false;
    *a = NumericTone(I32(t1, SKIN_PEEP_SLOT) >= 0 ? SlotPerson(I32(t1, SKIN_PEEP_SLOT)) : 0);
    *b = NumericTone(I32(t2, SKIN_PEEP_SLOT) >= 0 ? SlotPerson(I32(t2, SKIN_PEEP_SLOT)) : 0);
    return true;
}

// A villager who has no entry yet: a copy the game made of someone keeps their tone; a child of the couple (vf1fun's
// Spawn Child) inherits; anyone else is given a random tone. Babies are given theirs at the conception (BabiesMade).
static Entry *Newcomer(int slot) {
    const unsigned char *v = Villager(slot);
    for (int t = 0; t < (int)SKIN_HOUSEHOLD_SLOTS; ++t) {
        if (t == slot || !Exists(t)) continue;
        const unsigned char *o = Villager(t);
        if (I32(o, SKIN_VILLAGER_HEAD) != I32(v, SKIN_VILLAGER_HEAD) || I32(o, SKIN_VILLAGER_BODY) != I32(v, SKIN_VILLAGER_BODY))
            continue;
        Entry *source = SlotPerson(t);
        if (source && IsVillager(*source, v)) {
            Entry copy = *source;
            return Bind(slot, copy.tone, copy.birth, copy.person);
        }
    }
    int a = 0, b = 0;
    int tone = CoupleTones(v, &a, &b) ? Inherit(a, b) : RandomTone();
    return Bind(slot, tone, tone, 0);
}

static Entry *Person(int slot) {
    if (Suspended || !Exists(slot)) return 0;
    Entry *e = SlotPerson(slot);
    if (!e) e = Newcomer(slot);
    if (e) {
        const unsigned char *v = Villager(slot);
        e->head = I32(v, SKIN_VILLAGER_HEAD);
        e->body = I32(v, SKIN_VILLAGER_BODY);
    }
    return e;
}

// Who a Family Tree entry is: the person in the house it names (its villager slot, while the name and sex are theirs),
// the person who has this place, or the same person one generation over (Next Generation's heir is a child of one
// generation and a parent of the next). 0 when nobody is held for it.
static Entry *TreePerson(const unsigned char *peep, int g, int p) {
    int slot = I32(peep, SKIN_PEEP_SLOT);
    if (slot >= 0 && Exists(slot)) {
        Entry *e = Person(slot);
        if (e && IsPeep(*e, peep)) return e;
    }
    for (unsigned k = 0; k < EntryCount; ++k)
        if (HasPlace(Entries[k], g, p) && IsPeep(Entries[k], peep)) return &Entries[k];
    for (unsigned k = 0; k < EntryCount; ++k) {
        const Entry &e = Entries[k];
        if (!IsPeep(e, peep) || e.head != I32(peep, SKIN_PEEP_HEAD) || e.body != I32(peep, SKIN_PEEP_BODY)) continue;
        for (int j = 0; j < 2; ++j)
            if (e.gen[j] && (e.gen[j] == g + 1 || e.gen[j] == g - 1) && (e.place[j] < 2) != (p < 2))
                return &Entries[k];
    }
    return 0;
}

// The tree places of everybody held; for every tree entry of every generation nobody holds yet (`everyone`: the first
// load of a family), a random tone.
static void TreePass(bool everyone) {
    int gens = Generations();
    for (int g = 1; g <= gens; ++g) {
        unsigned char *rec = Record(g);
        if (!rec || !rec[0]) continue;
        int n = PlaceCount(rec);
        for (int p = 0; p < n; ++p) {
            unsigned char *peep = Peep(rec, p);
            if (!peep[SKIN_PEEP_VALID]) continue;
            Entry *e = TreePerson(peep, g, p);
            if (e) { AddPlace(*e, g, p); continue; }
            if (!everyone) continue;
            Entry *made = NewEntry();
            if (!made) return;
            made->gender = I32(peep, SKIN_PEEP_GENDER);
            CopyName(made->name, (const char *)peep);
            made->head = I32(peep, SKIN_PEEP_HEAD);
            made->body = I32(peep, SKIN_PEEP_BODY);
            made->tone = made->birth = (unsigned char)RandomTone();
            made->person = NextPerson++;
            AddPlace(*made, g, p);
        }
    }
}

static void Reconcile(bool everyone) {
    for (int s = 0; s < (int)SKIN_HOUSEHOLD_SLOTS; ++s) Person(s);
    TreePass(everyone);
}

// Before a save: only who is in the house or in the tree is kept.
static void Tidy() {
    Reconcile(false);
    for (unsigned i = 0; i < EntryCount;) {
        Entry &e = Entries[i];
        if (e.slot >= 0 && !(Exists(e.slot) && IsVillager(e, Villager(e.slot)))) e.slot = -1;
        for (int k = 0; k < 2; ++k) {
            unsigned char *rec = Record(e.gen[k]);
            if (!rec || e.place[k] < 0 || e.place[k] >= PlaceCount(rec) || !IsPeep(e, Peep(rec, e.place[k]))) {
                e.gen[k] = 0;
                e.place[k] = 0;
            }
        }
        if (!e.gen[0] && e.gen[1]) { e.gen[0] = e.gen[1]; e.place[0] = e.place[1]; e.gen[1] = e.place[1] = 0; }
        if (e.slot < 0 && !e.gen[0]) { Remove(i); continue; }
        ++i;
    }
    Reindex();
}

// ---------------------------------------------------------------- the tone a draw uses
static unsigned Drawn(const Entry *e) { return e && e->tone >= 1 && e->tone <= SKIN_TONE_COUNT ? e->tone : 0; }

static unsigned __cdecl ToneForSlot(int slot) {
    if (Suspended) return 0;
    return Drawn(Person(slot));
}

static unsigned __cdecl ToneForVillager(const unsigned char *v) { return ToneForSlot(SlotOf(v)); }

static unsigned __cdecl ToneForPeep(const unsigned char *peep) {
    int gen = 0, place = 0;
    if (Suspended || !peep[SKIN_PEEP_VALID]) return 0;
    if (!PlaceOf(peep, &gen, &place)) {
        // not one of the tree's own entries: a record another companion draws with the tree's own code (vf1revive's
        // remarried partner's late spouse, under the spouse): the person in the house it names
        int slot = I32(peep, SKIN_PEEP_SLOT);
        Entry *e = slot >= 0 && Exists(slot) ? Person(slot) : 0;
        return e && IsPeep(*e, peep) ? Drawn(e) : 0;
    }
    Entry *e = TreePerson(peep, gen, place);
    if (!e) return 0;
    AddPlace(*e, gen, place);
    return Drawn(e);
}

// The baby a mother carries: theGameState's reserved slots hold the babies of the one pregnancy there is.
static unsigned __cdecl BabyTone(const unsigned char *mother) {
    if (Suspended || !mother || !I32(mother, SKIN_VILLAGER_PREGNANT)) return 0;
    const unsigned char *gs = GameState();
    if (!gs) return 0;
    int baby = I32(gs, SKIN_GAME_STATE_RESERVED_BABY);
    return baby >= 0 && baby < (int)SKIN_HOUSEHOLD_SLOTS && Exists(baby) ? Drawn(Person(baby)) : 0;
}

// ================================================================ the masks (a 1-bit PNG each)
// inflate: RFC 1951, the whole stream into one buffer of the size the picture needs.
struct Bits { const unsigned char *p, *end; unsigned bit, n; bool bad; };
static unsigned Take(Bits &b, unsigned n) {
    while (b.n < n) {
        if (b.p >= b.end) { b.bad = true; return 0; }
        b.bit |= (unsigned)*b.p++ << b.n;
        b.n += 8;
    }
    unsigned v = b.bit & ((1u << n) - 1);
    b.bit >>= n;
    b.n -= n;
    return v;
}
struct Huffman { unsigned short count[16], symbol[320]; };
static bool Build(Huffman &h, const unsigned char *lengths, unsigned n) {
    unsigned short offs[16];
    for (unsigned k = 0; k < 16; ++k) h.count[k] = 0;
    for (unsigned k = 0; k < n; ++k) ++h.count[lengths[k]];
    if (h.count[0] == n) return true;
    int left = 1;
    for (unsigned len = 1; len < 16; ++len) {
        left <<= 1;
        left -= h.count[len];
        if (left < 0) return false;
    }
    offs[1] = 0;
    for (unsigned len = 1; len < 15; ++len) offs[len + 1] = (unsigned short)(offs[len] + h.count[len]);
    for (unsigned k = 0; k < n; ++k)
        if (lengths[k]) h.symbol[offs[lengths[k]]++] = (unsigned short)k;
    return true;
}
static int Decode(Bits &b, const Huffman &h) {
    int code = 0, first = 0, index = 0;
    for (unsigned len = 1; len < 16; ++len) {
        code |= (int)Take(b, 1);
        int count = h.count[len];
        if (code - count < first) return h.symbol[index + (code - first)];
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
        if (b.bad) return -1;
    }
    return -1;
}
static const unsigned short LengthBase[29] = { 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
                                               67, 83, 99, 115, 131, 163, 195, 227, 258 };
static const unsigned char LengthExtra[29] = { 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4,
                                               5, 5, 5, 5, 0 };
static const unsigned short DistBase[30] = { 1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
                                             769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577 };
static const unsigned char DistExtra[30] = { 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10,
                                             11, 11, 12, 12, 13, 13 };

static bool Codes(Bits &b, unsigned char *out, unsigned cap, unsigned &at, const Huffman &lit, const Huffman &dist) {
    for (;;) {
        int sym = Decode(b, lit);
        if (sym < 0 || b.bad) return false;
        if (sym < 256) {
            if (at >= cap) return false;
            out[at++] = (unsigned char)sym;
        } else if (sym == 256) {
            return true;
        } else {
            sym -= 257;
            if (sym >= 29) return false;
            unsigned len = LengthBase[sym] + Take(b, LengthExtra[sym]);
            int d = Decode(b, dist);
            if (d < 0 || d >= 30 || b.bad) return false;
            unsigned back = DistBase[d] + Take(b, DistExtra[d]);
            if (b.bad || back > at || len > cap - at) return false;
            for (unsigned k = 0; k < len; ++k, ++at) out[at] = out[at - back];
        }
    }
}

static bool Inflate(const unsigned char *in, unsigned n, unsigned char *out, unsigned cap, unsigned *made) {
    Bits b = { in, in + n, 0, 0, false };
    unsigned at = 0;
    static Huffman lit, dist;
    for (;;) {
        unsigned last = Take(b, 1), type = Take(b, 2);
        if (b.bad) return false;
        if (type == 0) {
            b.bit = 0;
            b.n = 0;
            if (b.end - b.p < 4) return false;
            unsigned len = b.p[0] | b.p[1] << 8, nlen = b.p[2] | b.p[3] << 8;
            b.p += 4;
            if (len != (~nlen & 0xFFFF) || (unsigned)(b.end - b.p) < len || len > cap - at) return false;
            Copy(out + at, b.p, len);
            b.p += len;
            at += len;
        } else if (type == 1) {
            unsigned char lengths[288];
            unsigned k = 0;
            for (; k < 144; ++k) lengths[k] = 8;
            for (; k < 256; ++k) lengths[k] = 9;
            for (; k < 280; ++k) lengths[k] = 7;
            for (; k < 288; ++k) lengths[k] = 8;
            Build(lit, lengths, 288);
            for (k = 0; k < 30; ++k) lengths[k] = 5;
            Build(dist, lengths, 30);
            if (!Codes(b, out, cap, at, lit, dist)) return false;
        } else if (type == 2) {
            static const unsigned char order[19] = { 16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15 };
            unsigned nlen = Take(b, 5) + 257, ndist = Take(b, 5) + 1, ncode = Take(b, 4) + 4;
            if (b.bad || nlen > 286 || ndist > 30) return false;
            unsigned char lengths[320];
            Zero(lengths, sizeof lengths);
            for (unsigned k = 0; k < ncode; ++k) lengths[order[k]] = (unsigned char)Take(b, 3);
            Huffman code;
            if (!Build(code, lengths, 19)) return false;
            Zero(lengths, sizeof lengths);
            for (unsigned k = 0; k < nlen + ndist;) {
                int sym = Decode(b, code);
                if (sym < 0 || b.bad) return false;
                if (sym < 16) { lengths[k++] = (unsigned char)sym; continue; }
                unsigned char v = 0;
                unsigned rep;
                if (sym == 16) {
                    if (!k) return false;
                    v = lengths[k - 1];
                    rep = 3 + Take(b, 2);
                } else if (sym == 17) {
                    rep = 3 + Take(b, 3);
                } else {
                    rep = 11 + Take(b, 7);
                }
                if (k + rep > nlen + ndist) return false;
                while (rep--) lengths[k++] = v;
            }
            if (!lengths[256] || !Build(lit, lengths, nlen) || !Build(dist, lengths + nlen, ndist)) return false;
            if (!Codes(b, out, cap, at, lit, dist)) return false;
        } else {
            return false;
        }
        if (last) break;
    }
    *made = at;
    return true;
}

static unsigned Crc32(const unsigned char *p, unsigned n, unsigned crc = 0xFFFFFFFFu) {
    for (unsigned i = 0; i < n; ++i) {
        crc ^= p[i];
        for (int k = 0; k < 8; ++k) crc = crc & 1 ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
    }
    return crc;
}
static unsigned Big32(const unsigned char *p) { return (unsigned)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }

static unsigned char *ReadWhole(const wchar_t *path, unsigned *size, unsigned most) {
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return 0;
    DWORD high = 0, low = GetFileSize(h, &high);
    unsigned char *data = 0;
    if (low != INVALID_FILE_SIZE && !high && low && low <= most)
        data = (unsigned char *)VirtualAlloc(0, low, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD got = 0;
    if (data && (!ReadFile(h, data, low, &got, 0) || got != low)) {
        VirtualFree(data, 0, MEM_RELEASE);
        data = 0;
    }
    CloseHandle(h);
    *size = low;
    return data;
}

static const unsigned long long kFnvBasis = 0xCBF29CE484222325ull;
static const unsigned long long kFnvPrime = 0x100000001B3ull;
static unsigned long long Fnv(unsigned long long h, const unsigned char *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) { h ^= p[i]; h *= kFnvPrime; }
    return h;
}

// The mask of sheet i: one bit a pixel, row after row, `stride` bytes a row, the leftmost pixel in the top bit.
// Returns 0 unless the sheet file is the one the mask was made from and the mask is a 1-bit picture of its size.
static unsigned char *LoadMask(const SkinSheetInfo &info, unsigned *strideOut) {
    wchar_t path[MAX_PATH];
    Append(path, MAX_PATH, GameFolder, L"Images\\", info.file);
    unsigned size = 0;
    unsigned char *sheet = ReadWhole(path, &size, 64u << 20);
    if (!sheet) return 0;
    bool same = size == info.fileSize && Fnv(kFnvBasis, sheet, size) == info.fileHash;
    VirtualFree(sheet, 0, MEM_RELEASE);
    if (!same) return 0;
    Append(path, MAX_PATH, Folder, L"Skin Masks\\", info.file);
    unsigned char *png = ReadWhole(path, &size, 8u << 20);
    if (!png) return 0;
    static const unsigned char signature[8] = { 0x89, 'P', 'N', 'G', 13, 10, 26, 10 };
    unsigned char *result = 0, *idat = 0, *raw = 0;
    unsigned w = 0, h = 0, idatSize = 0, pos = 8;
    bool ok = size > 8;
    for (unsigned k = 0; ok && k < 8; ++k) ok = png[k] == signature[k];
    if (ok) idat = (unsigned char *)VirtualAlloc(0, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    ok = ok && idat;
    bool header = false, end = false;
    while (ok && !end) {
        if (size - pos < 12) { ok = false; break; }
        unsigned n = Big32(png + pos);
        if (n > size - pos - 12) { ok = false; break; }
        const unsigned char *kind = png + pos + 4, *body = png + pos + 8;
        if ((Crc32(kind, n + 4) ^ 0xFFFFFFFFu) != Big32(body + n)) { ok = false; break; }
        if (kind[0] == 'I' && kind[1] == 'H' && kind[2] == 'D' && kind[3] == 'R') {
            ok = n == 13 && body[8] == 1 && body[9] == 0 && body[10] == 0 && body[11] == 0 && body[12] == 0;
            w = Big32(body);
            h = Big32(body + 4);
            header = true;
        } else if (kind[0] == 'I' && kind[1] == 'D' && kind[2] == 'A' && kind[3] == 'T') {
            Copy(idat + idatSize, body, n);
            idatSize += n;
        } else if (kind[0] == 'I' && kind[1] == 'E' && kind[2] == 'N' && kind[3] == 'D') {
            end = true;
        }
        pos += n + 12;
    }
    ok = ok && header && end && (int)w == info.width && (int)h == info.height && idatSize > 6;
    const unsigned stride = (w + 7) / 8, line = stride + 1;
    unsigned made = 0;
    if (ok) ok = (idat[0] & 0x0F) == 8 && ((idat[0] << 8) | idat[1]) % 31 == 0 && !(idat[1] & 0x20);
    if (ok) raw = (unsigned char *)VirtualAlloc(0, line * h, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (ok && raw) ok = Inflate(idat + 2, idatSize - 6, raw, line * h, &made) && made == line * h;
    if (ok && raw) {
        unsigned a = 1, b = 0;
        for (unsigned i = 0; i < made; ++i) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
        ok = (b << 16 | a) == Big32(idat + idatSize - 4);
    }
    if (ok && raw) {
        // unfilter (bpp 1 byte for a 1-bit picture), then pack the rows together
        for (unsigned y = 0; y < h && ok; ++y) {
            unsigned char *row = raw + y * line + 1, *up = y ? raw + (y - 1) * line + 1 : 0;
            unsigned f = row[-1];
            for (unsigned x = 0; x < stride; ++x) {
                unsigned left = x ? row[x - 1] : 0, above = up ? up[x] : 0, corner = x && up ? up[x - 1] : 0;
                unsigned v = row[x];
                if (f == 1) v += left;
                else if (f == 2) v += above;
                else if (f == 3) v += (left + above) / 2;
                else if (f == 4) {
                    int p = (int)left + (int)above - (int)corner;
                    int pa = p > (int)left ? p - (int)left : (int)left - p;
                    int pb = p > (int)above ? p - (int)above : (int)above - p;
                    int pc = p > (int)corner ? p - (int)corner : (int)corner - p;
                    v += pa <= pb && pa <= pc ? left : pb <= pc ? above : corner;
                } else if (f != 0) {
                    ok = false;
                }
                row[x] = (unsigned char)v;
            }
        }
        if (ok) {
            for (unsigned y = 0; y < h; ++y) Copy(raw + y * stride, raw + y * line + 1, stride);
            result = raw;
            raw = 0;
            *strideOut = stride;
        }
    }
    if (raw) VirtualFree(raw, 0, MEM_RELEASE);
    if (idat) VirtualFree(idat, 0, MEM_RELEASE);
    VirtualFree(png, 0, MEM_RELEASE);
    return result;
}

// ================================================================ SDL (the game's own copies)
struct SdlFormat { unsigned format; void *palette; unsigned char bits, bytes, pad[2]; unsigned r, g, b, a; };
struct SdlSurface { unsigned flags; SdlFormat *format; int w, h, pitch; void *pixels; };
typedef SdlSurface *(__cdecl *CreateSurfaceFn)(unsigned flags, int w, int h, int depth, unsigned r, unsigned g,
                                               unsigned b, unsigned a);
typedef void (__cdecl *FreeSurfaceFn)(SdlSurface *);
static CreateSurfaceFn CreateSurface;
static FreeSurfaceFn FreeSurface;

// ---------------------------------------------------------------- the sheets
enum { SHEET_UNREAD = 0, SHEET_READY = 1, SHEET_REFUSED = 2 };
struct Sheet { int state; unsigned char *skin; unsigned stride; };
static Sheet Sheets[SKIN_SHEET_COUNT];

// The surface the game draws sheet i from now, and its cell height (0 when the game has not loaded it). Only read:
// the image table's grid (+0x2C) is made by the game's GetImageGrid on first use.
static SdlSurface *LiveSurface(int i, int *cellHeight) {
    const unsigned char *grid = *(unsigned char *const *)(SKIN_IMAGE_ENTRIES[i] + SKIN_IMAGE_ENTRY_GRID);
    if (!grid) return 0;
    void **holder;
    void ***parts = *(void ****)(grid + SKIN_GRID_FILES);
    if (parts) holder = parts[SkinSheetInfos[i].part];
    else if (SkinSheetInfos[i].part == 0) holder = *(void ***)(grid + SKIN_GRID_HOLDER);
    else return 0;
    if (!holder || !*holder) return 0;
    *cellHeight = *(const int *)(grid + SKIN_GRID_CELL_HEIGHT);
    return (SdlSurface *)*holder;
}

static unsigned Shift(unsigned mask) {
    unsigned n = 0;
    while (mask && !(mask & 1)) { mask >>= 1; ++n; }
    return n;
}

// ---------------------------------------------------------------- the recolour (patcher/vf1_skin_art.py, one row)
// The Virtual Villagers Fun Patcher's method, number for number (its vv_skin_tone_art.py shade / recolour /
// tone_scales / oklch_to_rgb; tests/test_skin_tone_draw.py holds these pixels to vf1_skin_art.py's on the real sheets).
static double CubeRoot(double v) {
    if (v <= 0) return 0;
    double x = v < 0.008 ? 0.2 : (v < 0.125 ? 0.4 : 0.8);
    for (int i = 0; i < 40; ++i) {
        double next = x - (x * x * x - v) / (3 * x * x);
        if (next == x) break;
        x = next;
    }
    return x;
}

static double Lightness(unsigned r, unsigned g, unsigned b) {       // OKLab lightness of an 8-bit colour
    const double lin[3] = { SkinLinear[r], SkinLinear[g], SkinLinear[b] };
    double L = 0;
    for (int i = 0; i < 3; ++i)
        L += SkinToLab[0][i] * CubeRoot(SkinToLms[i][0] * lin[0] + SkinToLms[i][1] * lin[1] + SkinToLms[i][2] * lin[2]);
    return L;
}

static bool Linear(double L, double chroma, const SkinTone &t, double out[3]) {
    const double lab[3] = { L, chroma * t.cosHue, chroma * t.sinHue };
    double lms[3];
    for (int i = 0; i < 3; ++i) {
        double v = SkinLabToLms[i][0] * lab[0] + SkinLabToLms[i][1] * lab[1] + SkinLabToLms[i][2] * lab[2];
        lms[i] = v * v * v;
    }
    bool inside = true;
    for (int i = 0; i < 3; ++i) {
        out[i] = SkinLmsToLinear[i][0] * lms[0] + SkinLmsToLinear[i][1] * lms[1] + SkinLmsToLinear[i][2] * lms[2];
        if (out[i] < -1e-4 || out[i] > 1 + 1e-4) inside = false;
    }
    return inside;
}

static unsigned Stored(double light) {
    unsigned lo = 0, hi = 255;
    while (lo < hi) {
        unsigned mid = (lo + hi) / 2;
        if (SkinEncode[mid] <= light) lo = mid + 1; else hi = mid;
    }
    return lo;
}

static double Min(double a, double b) { return a < b ? a : b; }
static double Max(double a, double b) { return a > b ? a : b; }

// oklch_to_rgb: the hue always kept; chroma gives way first, never below `floor`, then lightness moves toward `toward`.
static unsigned ToRgb(double L, double c, const SkinTone &t, double floor, double toward) {
    double out[3];
    floor = Min(floor, c);
    if (!Linear(L, floor, t, out)) {
        double lo = L, hi = toward;
        for (int i = 0; i < 14; ++i) {
            double mid = (lo + hi) / 2;
            if (Linear(mid, floor, t, out)) hi = mid; else lo = mid;
        }
        L = hi;
    }
    if (!Linear(L, c, t, out)) {
        double lo = floor, hi = c;
        for (int i = 0; i < 14; ++i) {
            double mid = (lo + hi) / 2;
            if (Linear(L, mid, t, out)) lo = mid; else hi = mid;
        }
        c = lo;
    }
    Linear(L, c, t, out);
    unsigned v[3];
    for (int i = 0; i < 3; ++i) v[i] = Stored(out[i] < 0 ? 0 : (out[i] > 1 ? 1 : out[i]));
    return v[0] | v[1] << 8 | v[2] << 16;
}

// One row of cells: each skin colour once, with how many skin pixels have it (the percentiles count pixels).
struct Colour { unsigned key; unsigned count; double light; unsigned value; };
enum { COLOUR_BITS = 17, COLOUR_SLOTS = 1 << COLOUR_BITS, COLOUR_MOST = COLOUR_SLOTS / 4 * 3 };
static Colour Colours[COLOUR_SLOTS];
static unsigned ColourOrder[COLOUR_SLOTS];
static unsigned ColourCount;

static void ClearColours() {
    for (unsigned k = 0; k < ColourCount; ++k) Colours[ColourOrder[k]].key = 0;
    ColourCount = 0;
}

static Colour *FindColour(unsigned rgb, bool add) {
    const unsigned key = rgb + 1;
    unsigned at = (key * 2654435761u) >> (32 - COLOUR_BITS);
    for (;;) {
        Colour &c = Colours[at];
        if (c.key == key) return &c;
        if (!c.key) {
            if (!add || ColourCount >= COLOUR_MOST) return 0;
            c.key = key;
            c.count = 0;
            c.light = Lightness(rgb & 0xFF, (rgb >> 8) & 0xFF, (rgb >> 16) & 0xFF);
            ColourOrder[ColourCount++] = at;
            return &c;
        }
        at = (at + 1) & (COLOUR_SLOTS - 1);
    }
}

static bool Lighter(unsigned a, unsigned b) { return Colours[a].light > Colours[b].light; }

static void SiftDown(unsigned *o, unsigned root, unsigned end) {
    while (2 * root + 1 < end) {
        unsigned child = 2 * root + 1;
        if (child + 1 < end && Lighter(o[child + 1], o[child])) ++child;
        if (!Lighter(o[child], o[root])) return;
        unsigned t = o[root]; o[root] = o[child]; o[child] = t;
        root = child;
    }
}

static void SortColours() {        // ColourOrder by lightness, darkest first (a heap sort: no library)
    unsigned *o = ColourOrder;
    const unsigned n = ColourCount;
    for (unsigned start = n / 2; start-- > 0;) SiftDown(o, start, n);
    for (unsigned end = n; end-- > 1;) {
        unsigned t = o[0]; o[0] = o[end]; o[end] = t;
        SiftDown(o, 0, end);
    }
}

static double LightAt(unsigned index) {       // the index-th of the row's skin lightnesses, darkest first
    unsigned seen = 0;
    for (unsigned k = 0; k < ColourCount; ++k) {
        seen += Colours[ColourOrder[k]].count;
        if (index < seen) return Colours[ColourOrder[k]].light;
    }
    return Colours[ColourOrder[ColourCount - 1]].light;
}

static double Percentile(unsigned pixels, unsigned q) {         // _percentile: between neighbours in a straight line
    const double at = (double)((pixels - 1) * q) / 100;
    const unsigned lo = (unsigned)at, hi = lo + 1 < pixels ? lo + 1 : pixels - 1;
    const double a = LightAt(lo), b = LightAt(hi);
    return a + (b - a) * (at - lo);
}

// tone_scales and shade: every colour of the row in tone t, the row's middle skin `mid`, its reach `down` and `up`.
static void ShadeColours(const SkinTone &t, double mid, double down, double up) {
    down *= SkinShading;
    up *= SkinShading;
    const double sDown0 = Max(Min(1.0, (t.L - SkinFloor) / Max(down, 1e-6)), 0.0);
    const double sUp0 = Max(Min(1.0, (SkinCeil - t.L) / Max(up, 1e-6)), 0.0);
    const double moreUp = Min(1 + SkinGive * (1 - sDown0), (SkinCeil - t.L) / Max(up, 1e-6));
    const double moreDown = Min(1 + SkinGive * (1 - sUp0), (t.L - SkinFloor) / Max(down, 1e-6));
    const double sDown = sUp0 < 1 ? moreDown : sDown0, sUp = sDown0 < 1 ? moreUp : sUp0;
    for (unsigned k = 0; k < ColourCount; ++k) {
        Colour &c = Colours[ColourOrder[k]];
        const double offset = (c.light - mid) * SkinShading;
        const double light = Min(Max(t.L + (offset < 0 ? offset * sDown : offset * sUp), SkinFloor), SkinCeil);
        const double depth = Min(Max(-offset / Max(down, 1e-6), 0.0), 1.0);
        c.value = ToRgb(light, t.chroma * (1 + SkinShadowChroma * depth), t, SkinChromaFloor * t.chroma, t.L);
    }
}

// ---------------------------------------------------------------- the recoloured rows
struct Row { SdlSurface *surface; unsigned short sheet, row; unsigned char tone; unsigned used; };
enum { ROW_COUNT = 1024 };
static const unsigned ROW_BYTES_MOST = 96u << 20;
static Row Rows[ROW_COUNT];
static unsigned RowClock, RowBytes;

static unsigned RowSize(const SdlSurface *s) { return (unsigned)s->pitch * (unsigned)s->h; }

static void DropOldest(const Row *keep) {
    Row *oldest = 0;
    for (int i = 0; i < ROW_COUNT; ++i)
        if (Rows[i].surface && &Rows[i] != keep && (!oldest || Rows[i].used < oldest->used)) oldest = &Rows[i];
    if (!oldest) return;
    RowBytes -= RowSize(oldest->surface);
    FreeSurface(oldest->surface);
    oldest->surface = 0;
    --VF1Skin_Status.rows;
}

static SdlSurface *MakeRow(int i, const SdlSurface *from, int cellHeight, int row, unsigned tone) {
    const SdlFormat *f = from->format;
    SdlSurface *made = CreateSurface(0, from->w, cellHeight, 32, f->r, f->g, f->b, f->a);
    if (!made) return 0;
    if (made->w != from->w || made->h != cellHeight || made->pitch < from->w * 4 || made->format->bytes != 4) {
        FreeSurface(made);
        return 0;
    }
    unsigned short control = 0, precise = 0x27F;        // the recolour at double precision, whatever the game set
    __asm { fnstcw control }
    __asm { fldcw precise }
    const Sheet &s = Sheets[i];
    const unsigned rs = Shift(f->r), gs = Shift(f->g), bs = Shift(f->b), as = Shift(f->a);
    const unsigned keep = ~(f->r | f->g | f->b);
    // 1. the row's skin colours, each with how many skin pixels have it
    unsigned pixels = 0;
    bool ok = true;
    for (int y = 0; y < cellHeight && ok; ++y) {
        const int sy = row * cellHeight + y;
        const unsigned *in = (const unsigned *)((const unsigned char *)from->pixels + sy * from->pitch);
        const unsigned char *skin = s.skin + (unsigned)sy * s.stride;
        for (int x = 0; x < from->w; ++x) {
            const unsigned p = in[x];
            if ((skin[x >> 3] >> (7 - (x & 7))) & 1 && (!f->a || (p >> as) & 0xFF)) {
                Colour *c = FindColour(((p >> rs) & 0xFF) | ((p >> gs) & 0xFF) << 8 | ((p >> bs) & 0xFF) << 16, true);
                if (!c) { ok = false; break; }
                ++c->count;
                ++pixels;
            }
        }
    }
    // 2. the row's middle skin and its reach (2nd, 50th, 98th percentiles), and each colour in the tone
    if (ok && pixels) {
        SortColours();
        const double lo = Percentile(pixels, SkinPercentiles[0]), mid = Percentile(pixels, SkinPercentiles[1]),
                     hi = Percentile(pixels, SkinPercentiles[2]);
        ShadeColours(SkinTones[tone], mid, mid - lo, hi - mid);
    }
    // 3. the copy: the skin in the tone, everything else (and all alpha) as it is
    for (int y = 0; y < cellHeight && ok; ++y) {
        const int sy = row * cellHeight + y;
        const unsigned *in = (const unsigned *)((const unsigned char *)from->pixels + sy * from->pitch);
        unsigned *out = (unsigned *)((unsigned char *)made->pixels + y * made->pitch);
        const unsigned char *skin = s.skin + (unsigned)sy * s.stride;
        for (int x = 0; x < from->w; ++x) {
            unsigned p = in[x];
            if ((skin[x >> 3] >> (7 - (x & 7))) & 1 && (!f->a || (p >> as) & 0xFF)) {
                const unsigned c = FindColour(((p >> rs) & 0xFF) | ((p >> gs) & 0xFF) << 8 | ((p >> bs) & 0xFF) << 16,
                                              false)->value;
                p = (p & keep) | (c & 0xFF) << rs | ((c >> 8) & 0xFF) << gs | ((c >> 16) & 0xFF) << bs;
            }
            out[x] = p;
        }
    }
    ClearColours();
    __asm { fldcw control }
    if (!ok) {                     // more colours than the table holds: this row is drawn as the game draws it
        FreeSurface(made);
        return 0;
    }
    ++VF1Skin_Status.made;
    return made;
}

static SdlSurface *RowFor(int sheet, const SdlSurface *from, int cellHeight, int row, unsigned tone) {
    unsigned at = ((unsigned)sheet * 131u + (unsigned)row * 11u + tone) % ROW_COUNT;
    Row *free_ = 0;
    for (int probe = 0; probe < ROW_COUNT; ++probe) {
        Row &r = Rows[(at + probe) % ROW_COUNT];
        if (r.surface && r.sheet == sheet && r.row == row && r.tone == tone) { r.used = ++RowClock; return r.surface; }
        if (!r.surface && !free_) free_ = &r;
    }
    if (!free_) { DropOldest(0); return 0; }       // full: this draw is the game's own, the next finds room
    SdlSurface *made = MakeRow(sheet, from, cellHeight, row, tone);
    if (!made) return 0;
    free_->surface = made;
    free_->sheet = (unsigned short)sheet;
    free_->row = (unsigned short)row;
    free_->tone = (unsigned char)tone;
    free_->used = ++RowClock;
    RowBytes += RowSize(made);
    ++VF1Skin_Status.rows;
    while (RowBytes > ROW_BYTES_MOST) DropOldest(free_);
    VF1Skin_Status.bytes = RowBytes;
    return made;
}

// ================================================================ the hooks
static volatile unsigned CurrentTone;      // the tone of the person being drawn, 0 for none

struct BlitArgs { SdlSurface *surface; int x, y, left, top, right, bottom; };

static void __cdecl SwapBlit(BlitArgs *a) {
    const unsigned tone = CurrentTone;
    if (!tone || tone > SKIN_TONE_COUNT || !a->surface) return;
    for (int i = 0; i < SKIN_SHEET_COUNT; ++i) {
        int cellHeight = 0;
        SdlSurface *live = LiveSurface(i, &cellHeight);
        if (live != a->surface) continue;
        const SkinSheetInfo &info = SkinSheetInfos[i];
        Sheet &s = Sheets[i];
        if (s.state == SHEET_UNREAD) {
            s.skin = LoadMask(info, &s.stride);
            s.state = s.skin ? SHEET_READY : SHEET_REFUSED;
            if (s.skin) ++VF1Skin_Status.sheets; else ++VF1Skin_Status.refused;
        }
        if (s.state != SHEET_READY || live->w != info.width || live->h != info.height || cellHeight <= 0
            || live->format->bytes != 4 || a->top < 0 || a->bottom > live->h || a->top >= a->bottom)
            return;
        if (info.image == 0x68u) {                    // carrying.png: only the held baby (cell 3) is toned
            const int cell = live->w / SKIN_CARRYING_COLUMNS;
            if (a->right <= SKIN_BABY_CELL * cell || a->left >= (SKIN_BABY_CELL + 1) * cell) return;
        }
        const int row = a->top / cellHeight;
        if (a->bottom > (row + 1) * cellHeight) return;      // more than one row: not a cell
        SdlSurface *made = RowFor(i, live, cellHeight, row, tone);
        if (!made) return;
        a->surface = made;
        a->top -= row * cellHeight;
        a->bottom -= row * cellHeight;
        ++VF1Skin_Status.swapped;
        return;
    }
}

// Inline assembly cannot read the generated header's enums and `u` suffixes: the indices and offsets it uses, checked.
#define E_BLIT 0
#define E_DRAW 1
#define E_PORTRAIT 2
#define E_EVENT 3
#define C_PARENT1 2
#define C_PARENT2 3
#define C_CHILD 4
#define OFF_PARENT1 4
#define OFF_PARENT2 0DCh
#define OFF_CHILD 1B8h
typedef char AsmIndexCheck[SKIN_ENTRY_BLIT == E_BLIT && SKIN_ENTRY_DRAW_VILLAGER == E_DRAW && SKIN_ENTRY_PORTRAIT ==
                           E_PORTRAIT && SKIN_ENTRY_EVENT_PORTRAIT == E_EVENT && SKIN_CALL_TREE_PARENT1 == C_PARENT1 &&
                           SKIN_CALL_TREE_PARENT2 == C_PARENT2 && SKIN_CALL_TREE_CHILD == C_CHILD &&
                           SKIN_TREE_PARENT1_REGISTER_OFFSET == 0x4 && SKIN_TREE_PARENT2_REGISTER_OFFSET == 0xDC &&
                           SKIN_TREE_CHILD_REGISTER_OFFSET == 0x1B8 ? 1 : -1];

// ---- the trampolines and the entry hooks' frames (one per hook: none of these functions is ever re-entered)
__declspec(align(4096)) static unsigned char Trampolines[4096];
static void *EntryNext[4];                 // SKIN_ENTRY_*: where the game's own code goes on
static unsigned EntryReturn[4], EntryTone[4];
static void *CallNext[8];                  // SKIN_CALL_*: what each retargeted call called before
static unsigned CallReturn[8], CallTone[8];

static __declspec(naked) void BlitHook() {
    __asm {
        cmp dword ptr [CurrentTone], 0
        je go
        pushad
        lea eax, [esp + 24h]
        push eax
        call SwapBlit
        add esp, 4
        popad
    go:
        jmp dword ptr [EntryNext + 4 * E_BLIT]
    }
}

// Each hook: work out the tone, note it (keeping the one before), run the game's own function with the very same
// stack, put the tone before back.
#define TONED_CALL(retArray, toneArray, k, nextArray)            \
    __asm mov edx, dword ptr [CurrentTone]                                  \
    __asm mov dword ptr [toneArray + 4 * k], edx                            \
    __asm mov dword ptr [CurrentTone], eax                                  \
    __asm popad                                                             \
    __asm pop dword ptr [retArray + 4 * k]                                  \
    __asm call dword ptr [nextArray + 4 * k]                                \
    __asm push eax                                                          \
    __asm mov eax, dword ptr [toneArray + 4 * k]                            \
    __asm mov dword ptr [CurrentTone], eax                                  \
    __asm pop eax                                                           \
    __asm jmp dword ptr [retArray + 4 * k]

static __declspec(naked) void DrawVillagerHook() {
    __asm {
        pushad
        push dword ptr [esp + 24h]
        call ToneForSlot
        add esp, 4
    }
    TONED_CALL(EntryReturn, EntryTone, E_DRAW, EntryNext)
}

static __declspec(naked) void PortraitHook() {
    __asm {
        pushad
        push ecx
        call ToneForVillager
        add esp, 4
    }
    TONED_CALL(EntryReturn, EntryTone, E_PORTRAIT, EntryNext)
}

static __declspec(naked) void EventPortraitHook() {
    __asm {
        pushad
        push ecx
        call ToneForVillager
        add esp, 4
    }
    TONED_CALL(EntryReturn, EntryTone, E_EVENT, EntryNext)
}

static __declspec(naked) void TreeParent1Hook() {
    __asm {
        pushad
        lea eax, [edi + OFF_PARENT1]
        push eax
        call ToneForPeep
        add esp, 4
    }
    TONED_CALL(CallReturn, CallTone, C_PARENT1, CallNext)
}

static __declspec(naked) void TreeParent2Hook() {
    __asm {
        pushad
        lea eax, [edi + OFF_PARENT2]
        push eax
        call ToneForPeep
        add esp, 4
    }
    TONED_CALL(CallReturn, CallTone, C_PARENT2, CallNext)
}

static __declspec(naked) void TreeChildHook() {
    __asm {
        pushad
        lea eax, [ebp + OFF_CHILD]
        push eax
        call ToneForPeep
        add esp, 4
    }
    TONED_CALL(CallReturn, CallTone, C_CHILD, CallNext)
}

// The carried-items draw: inside it only the held baby (carrying.png cell 3) may be toned, in the baby's tone.
typedef void (__thiscall *CarriedFn)(void *manager, void *villager, int x, int y);
static void __fastcall Carried1Hook(void *manager, void *, void *villager, int x, int y) {
    unsigned before = CurrentTone;
    CurrentTone = BabyTone((const unsigned char *)villager);
    ((CarriedFn)CallNext[SKIN_CALL_CARRIED_1])(manager, villager, x, y);
    CurrentTone = before;
}
static void __fastcall Carried2Hook(void *manager, void *, void *villager, int x, int y) {
    unsigned before = CurrentTone;
    CurrentTone = BabyTone((const unsigned char *)villager);
    ((CarriedFn)CallNext[SKIN_CALL_CARRIED_2])(manager, villager, x, y);
    CurrentTone = before;
}

// ---- the conception: the babies are made, hidden, in the reserved slots; each is given its tone now, once.

// The father: the conception step passes the patriarch's head and body (0x48EB99..0x48EBB2; its name argument is the
// constant "Joey"), so he is the father when they are his (as vf1logs.dll finds him).
typedef unsigned char *(__thiscall *ManagerFn)(void *manager);
static Entry *FatherOf(int head, int body) {
    const unsigned char *p = ((ManagerFn)SKIN_FN_GET_PATRIARCH)(Manager());
    int slot = SlotOf(p);
    if (slot < 0 || I32(p, SKIN_VILLAGER_HEAD) != head || I32(p, SKIN_VILLAGER_BODY) != body) return 0;
    return Person(slot);
}

static void BabiesMade(const unsigned char *mother, int head, int body) {
    const unsigned char *gs = GameState();
    if (!gs || Suspended) return;
    int motherSlot = SlotOf(mother);
    int m = NumericTone(motherSlot >= 0 ? Person(motherSlot) : 0);
    int f = NumericTone(FatherOf(head, body));
    int first = 0;
    for (int k = 0; k < 3; ++k) {
        int slot = I32(gs, SKIN_GAME_STATE_RESERVED_BABY + 4u * (unsigned)k);
        const unsigned char *v = Villager(slot);
        // a baby of this conception: a record made and hidden until the birth (a slot still reserved from an earlier
        // pregnancy holds someone in the house, or nobody)
        if (!v || slot == motherSlot || !v[SKIN_VILLAGER_NAME] || v[SKIN_VILLAGER_PRESENT]) continue;
        if (!first) first = Inherit(f, m);           // the first baby's roll; twins and triplets copy it
        Bind(slot, first, first, 0);
        ++VF1Skin_Status.babies;
    }
}

typedef bool (__thiscall *ImpregnateFn)(void *villager, int one, const char *father, int head, int body, int flag);
static bool __fastcall ConceptionWrapper(void *mother, void *, int one, const char *father, int head, int body, int flag) {
    bool ok = ((ImpregnateFn)CallNext[SKIN_CALL_CONCEPTION])(mother, one, father, head, body, flag);
    if (ok) BabiesMade((const unsigned char *)mother, head, body);
    return ok;
}

// ---- renames: the entry follows the name the game gives (it calls ChangeName first, then copies the name in)
typedef void (__thiscall *ChangeNameFn)(void *tree, void *villager, const char *name);
static void Renamed(const void *villager, const char *name) {
    int slot = SlotOf(villager);
    if (slot < 0 || !name) return;
    Entry *e = SlotPerson(slot);
    if (!e) return;
    CopyName(e->name, name);
    for (unsigned k = 0; k < EntryCount; ++k)          // a copy of them (the same person) follows too
        if (&Entries[k] != e && Entries[k].person == e->person && Entries[k].slot < 0) CopyName(Entries[k].name, name);
}
static void __fastcall ChangeName1Hook(void *tree, void *, void *villager, const char *name) {
    ((ChangeNameFn)CallNext[SKIN_CALL_CHANGE_NAME_1])(tree, villager, name);
    Renamed(villager, name);
}
static void __fastcall ChangeName2Hook(void *tree, void *, void *villager, const char *name) {
    ((ChangeNameFn)CallNext[SKIN_CALL_CHANGE_NAME_2])(tree, villager, name);
    Renamed(villager, name);
}

// ================================================================ the file
// The Up to 28 Children sidecar's layout (vf1kids.cpp) with its own tag: "VF1SKIN\0", version 1, "VF1V101\0", file
// size, save file FNV-1a 64 and size, generations, parent 1 slot and gender, entry count, the entries (kEntry bytes
// each), FNV-1a 64 of everything before it.
typedef bool (__thiscall *GameStateSlotFn)(void *state, int slot);
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
static GameStateSlotFn NextLoad, NextSave;

static const unsigned kHeader = 52;
static const unsigned kMaxFile = kHeader + kMaxEntries * kEntry + 8;
static const unsigned kVersion = 1;
static unsigned char FileBuffer[kMaxFile];
static unsigned char HashBuffer[0x10000];

struct Sidecar { unsigned long long saveHash; unsigned saveSize; int generations, parentSlot, parentGender; unsigned count;
                 Entry entries[kMaxEntries]; };
static Sidecar Loaded, BackupFile, MineFile, OldFile;

static void Put32(unsigned char *p, unsigned v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24); }
static unsigned Get32(const unsigned char *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((unsigned)p[3] << 24); }

enum { FILE_MISSING = 0, FILE_OK = 1, FILE_DAMAGED = -1, FILE_SHUT = -2, FILE_FOREIGN = -3 };
static const unsigned kOpenTries = 5;
static const DWORD kOpenWaitMs = 250;

static bool Transient(DWORD e) { return e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION || e == ERROR_ACCESS_DENIED; }

static HANDLE OpenForRead(const char *path, DWORD *error) {
    for (unsigned k = 0;; ++k) {
        HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
        if (h != INVALID_HANDLE_VALUE) { *error = 0; return h; }
        DWORD e = GetLastError();
        if (!Transient(e) || k + 1 >= kOpenTries) { *error = e; return h; }
        Sleep(kOpenWaitMs);
    }
}

static int OpenFailure(DWORD e) { return e == ERROR_FILE_NOT_FOUND || e == ERROR_PATH_NOT_FOUND ? FILE_MISSING : FILE_SHUT; }

static int HashFile(const char *path, unsigned long long *hash, unsigned *size) {
    DWORD error = 0;
    HANDLE h = OpenForRead(path, &error);
    if (h == INVALID_HANDLE_VALUE) return OpenFailure(error);
    unsigned long long v = kFnvBasis;
    unsigned total = 0;
    int r = FILE_OK;
    for (;;) {
        DWORD got = 0;
        if (!ReadFile(h, HashBuffer, sizeof(HashBuffer), &got, 0)) { r = FILE_SHUT; break; }
        if (!got) break;
        v = Fnv(v, HashBuffer, got);
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
    const char *save = ((MakePathFn)vtable[SKIN_LDW_PATH_VSLOT / 4])(state, slot);
    if (!save) return false;
    unsigned n = Length(save);
    if (n == 0 || n + 1 >= MAX_PATH) return false;
    if (saveOut) Copy(saveOut, save, n + 1);
    unsigned cut = n;
    while (cut > 0 && save[cut - 1] != '\\' && save[cut - 1] != '/') --cut;
    if (cut == 0 || cut == n) return false;
    static const char middle[] = "Virtual Families 1 Patcher Data\\Skin Tones\\";
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

static void EnsureFolders(const char *tones) {
    char path[MAX_PATH];
    unsigned n = Length(tones);
    if (n + 1 >= MAX_PATH) return;
    Copy(path, tones, n + 1);
    unsigned cut = n;
    while (cut > 0 && path[cut - 1] != '\\') --cut;
    if (cut > 1) {
        path[cut - 1] = 0;
        CreateDirectoryA(path, 0);
        path[cut - 1] = '\\';
    }
    CreateDirectoryA(path, 0);
}

static bool EntryValid(const Entry &e) {
    if (e.slot < -1 || e.slot >= (int)SKIN_HOUSEHOLD_SLOTS || (e.gender != 0 && e.gender != 1) || e.name[25] != 0) return false;
    if (!((e.tone >= 1 && e.tone <= SKIN_TONE_COUNT) || e.tone == TONE_DEFAULT || e.tone == TONE_NONE)) return false;
    if (e.birth > SKIN_TONE_COUNT) return false;
    for (int k = 0; k < 2; ++k)
        if (e.gen[k] < 0 || e.gen[k] > (int)SKIN_TREE_GENERATIONS || e.place[k] < 0 || e.place[k] >= PLACES) return false;
    return true;
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
    static const unsigned char magic[8] = { 'V', 'F', '1', 'S', 'K', 'I', 'N', 0 };
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
        Copy(&out->entries[i], FileBuffer + kHeader + i * kEntry, kEntry);
        if (!EntryValid(out->entries[i])) return FILE_DAMAGED;
    }
    out->saveHash = Get32(FileBuffer + 24) | ((unsigned long long)Get32(FileBuffer + 28) << 32);
    out->saveSize = Get32(FileBuffer + 32);
    out->generations = (int)Get32(FileBuffer + 36);
    out->parentSlot = (int)Get32(FileBuffer + 40);
    out->parentGender = (int)Get32(FileBuffer + 44);
    out->count = count;
    return FILE_OK;
}

static bool WriteSidecar(const char *path, const char *folder, unsigned long long saveHash, unsigned saveSize) {
    unsigned char *rec = Record(Generations());
    unsigned size = kHeader + EntryCount * kEntry + 8;
    Zero(FileBuffer, kHeader);
    Copy(FileBuffer, "VF1SKIN\0", 8);
    Put32(FileBuffer + 8, kVersion);
    Copy(FileBuffer + 12, "VF1V101\0", 8);
    Put32(FileBuffer + 20, size);
    Put32(FileBuffer + 24, (unsigned)saveHash);
    Put32(FileBuffer + 28, (unsigned)(saveHash >> 32));
    Put32(FileBuffer + 32, saveSize);
    Put32(FileBuffer + 36, (unsigned)Generations());
    Put32(FileBuffer + 40, rec ? (unsigned)I32(rec, SKIN_RECORD_PARENT1 + SKIN_PEEP_SLOT) : 0xFFFFFFFFu);
    Put32(FileBuffer + 44, rec ? (unsigned)I32(rec, SKIN_RECORD_PARENT1 + SKIN_PEEP_GENDER) : 0xFFFFFFFFu);
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
    unsigned char *rec = Record(Generations());
    if (!rec) return false;
    return file.generations == Generations()
        && file.parentSlot == I32(rec, SKIN_RECORD_PARENT1 + SKIN_PEEP_SLOT)
        && file.parentGender == I32(rec, SKIN_RECORD_PARENT1 + SKIN_PEEP_GENDER);
}

static void Adopt(const Sidecar &file) {
    ClearEntries();
    for (unsigned i = 0; i < file.count; ++i) Entries[i] = file.entries[i];
    EntryCount = file.count;
    NextPerson = 1;
    for (unsigned i = 0; i < EntryCount; ++i)
        if (Entries[i].person >= NextPerson) NextPerson = Entries[i].person + 1;
    Reindex();
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

static void AfterLoad(void *state, int slot) {
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    Suspended = false;
    ClearEntries();
    if (!SidecarPath(state, slot, path, sizeof(path), save, folder)) { Reconcile(true); return; }
    unsigned long long hash = 0;
    unsigned size = 0;
    bool hashed = HashFile(save, &hash, &size) == FILE_OK;
    int r = ReadSidecar(path, &Loaded);
    VF1Skin_Status.lastLoad = 4;
    if (r == FILE_SHUT) {
        Suspended = true;
        VF1Skin_Status.lastLoad = 6;
        Log("slot %u: the skin tones' file could not be opened (in use?); it is left as it is and nobody is toned", (unsigned)slot);
        return;
    }
    if (r == FILE_DAMAGED) {
        bool moved = MoveAside(path);
        VF1Skin_Status.lastLoad = moved ? 5 : 7;
        Log(moved ? "slot %u: an unreadable skin tones' file was moved aside"
                  : "slot %u: an unreadable skin tones' file could not be moved aside; it is left as it is", (unsigned)slot);
        if (!moved) { Suspended = true; return; }
    }
    if (r == FILE_OK && hashed && Loaded.saveHash == hash && Loaded.saveSize == size) {
        Adopt(Loaded);
        Reconcile(false);
        VF1Skin_Status.lastLoad = 1;
        return;
    }
    if (hashed && SidecarPath(state, slot + (int)SKIN_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0)
        && ReadSidecar(backup, &BackupFile) == FILE_OK && BackupFile.saveHash == hash && BackupFile.saveSize == size) {
        Adopt(BackupFile);
        Reconcile(false);
        VF1Skin_Status.lastLoad = 2;
        return;
    }
    if (r == FILE_OK && SameFamily(Loaded)) {
        Adopt(Loaded);
        Reconcile(false);
        VF1Skin_Status.lastLoad = 3;
        return;
    }
    Reconcile(true);          // no file for this save: everybody of the family is given a random tone, once
}

static bool __fastcall GameStateLoad(void *state, void *, int slot) {
    bool loaded = NextLoad(state, slot);
    if (loaded && slot >= 1 && slot <= 5) AfterLoad(state, slot);
    return loaded;
}

// vf1kids.cpp RotateSidecars, for this folder (a save while the loaded save's file is shut never comes here).
static bool RotateSidecars(const char *path, const char *save, const char *backup, const char *backupSave) {
    int mine = Classify(path, save, &MineFile);
    bool backups = mine == FILE_FOREIGN && Describes(MineFile, backupSave) == FILE_OK;
    if (mine == FILE_SHUT) return false;
    int old = Classify(backup, backupSave, &OldFile);
    bool clear = old == FILE_MISSING;
    if (old == FILE_OK) clear = DeleteFileA(backup) != 0;
    else if (old == FILE_DAMAGED || old == FILE_FOREIGN) clear = MoveAside(backup);
    if (mine == FILE_OK) {
        if (clear) MoveFileExA(path, backup, 0);
    } else if (backups) {
        DeleteFileA(path);
    } else if (mine == FILE_DAMAGED || mine == FILE_FOREIGN) {
        if (!MoveAside(path)) return false;
    }
    return true;
}

static bool __fastcall GameStateSave(void *state, void *, int slot) {
    if (slot <= 0) return NextSave(state, slot);       // 0 is the options; every save FILE has its own (N, N + 20)
    if (Suspended) {                                   // the loaded save's file is shut: no file of it is touched
        VF1Skin_Status.lastSave = 4;
        return NextSave(state, slot);
    }
    char path[kSidecarPathCap], save[MAX_PATH], folder[kSidecarPathCap];
    char backup[kSidecarPathCap], backupSave[MAX_PATH];
    bool named = SidecarPath(state, slot, path, sizeof(path), save, folder)
        && SidecarPath(state, slot + (int)SKIN_SAVE_BACKUP_OFFSET, backup, sizeof(backup), backupSave, 0);
    bool writable = named && RotateSidecars(path, save, backup, backupSave);
    bool saved = NextSave(state, slot);
    if (!saved || !named) return saved;
    if (!writable) { VF1Skin_Status.lastSave = 4; return saved; }
    Tidy();
    if (!EntryCount) { VF1Skin_Status.lastSave = 2; return saved; }
    unsigned long long hash = 0;
    unsigned size = 0;
    if (HashFile(save, &hash, &size) == FILE_OK && WriteSidecar(path, folder, hash, size)) {
        VF1Skin_Status.lastSave = 1;
    } else {
        VF1Skin_Status.lastSave = 3;
        Log("slot %u: the skin tones' file could not be written", (unsigned)slot);
    }
    return saved;
}

// ================================================================ for vf1fun's Change Appearance and for Revive
typedef void (__cdecl *LogsEventFn)(int kind, int who, int a, int b);
enum { LOGS_APPEARANCE = 8 };      // vf1logs.cpp EV_APPEARANCE: "Appearance changed", Old / New skin tone

static unsigned char ShownTone(unsigned char tone) { return tone >= 1 && tone <= SKIN_TONE_COUNT ? tone : TONE_DEFAULT; }

static void SetTone(Entry *e, unsigned char tone, int slot, bool logged) {
    unsigned char before = e->tone;
    unsigned person = e->person;
    for (unsigned k = 0; k < EntryCount; ++k)
        if (Entries[k].person == person) Entries[k].tone = tone;
    if (!logged || ShownTone(before) == ShownTone(tone)) return;
    HMODULE logs = GetModuleHandleW(L"vf1logs.dll");
    LogsEventFn event = logs ? (LogsEventFn)GetProcAddress(logs, "VF1Logs_Event") : 0;
    if (event) event(LOGS_APPEARANCE, slot, ShownTone(before), ShownTone(tone));
}

// A family member's tone: *tone 1..10 or 15 (Game's own), *birth 0..10. 0 when the feature is not installed or the slot
// holds nobody.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_Get(int slot, int *tone, int *birth) {
    if (!VF1Skin_Status.installed || Suspended) return 0;
    Entry *e = Person(slot);
    if (!e) return 0;
    if (tone) *tone = ShownTone(e->tone);
    if (birth) *birth = e->birth;
    return 1;
}

// Change Appearance: `tone` 1..10, or 15 for Game's own (the game's own skin). An "Appearance changed" record is written
// to the Family History log (vf1logs.dll, when it is there) when the tone shown changes.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_Set(int slot, int tone) {
    if (!VF1Skin_Status.installed || Suspended || !((tone >= 1 && tone <= SKIN_TONE_COUNT) || tone == TONE_DEFAULT)) return 0;
    Entry *e = Person(slot);
    if (!e) return 0;
    SetTone(e, (unsigned char)tone, slot, true);
    return 1;
}

// "Reset to birth tone": the tone they were born with or first given, logged like any change. 0 when there is none.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_Reset(int slot) {
    if (!VF1Skin_Status.installed || Suspended) return 0;
    Entry *e = Person(slot);
    if (!e || e->birth < 1 || e->birth > SKIN_TONE_COUNT) return 0;
    SetTone(e, e->birth, slot, true);
    return 1;
}

// A tone's name as the menus and the log write it: "Copper", "Game's own" (15 or 0).
extern "C" __declspec(dllexport) const char *__cdecl VF1Skin_ToneName(int tone) {
    return tone >= 1 && tone <= SKIN_TONE_COUNT ? SkinTones[tone].name : SkinTones[0].name;
}

// For Revive a Family Member (vf1revive.dll): the two bytes to keep in its snapshot at a death. Returns the tone (0
// none, 1..10, 15 Game's own) and puts the birth tone in *birth; 0 and 0 when skin tones are off.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_ToneOf(int slot, int *birth) {
    if (birth) *birth = 0;
    if (!VF1Skin_Status.installed || Suspended) return 0;
    Entry *e = Exists(slot) ? SlotPerson(slot) : 0;
    if (!e) return 0;
    if (birth) *birth = e->birth;
    return e->tone;
}

// ... and to give them back to the villager it revived (in `slot`), as they were. Nothing is logged. Returns 1 when
// given; 0 when skin tones are off or the values are not a tone's.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_ToneGive(int slot, int tone, int birth) {
    if (!VF1Skin_Status.installed || Suspended || !Exists(slot)) return 0;
    if (!((tone >= 1 && tone <= SKIN_TONE_COUNT) || tone == TONE_DEFAULT || tone == TONE_NONE)) return 0;
    if (birth < 0 || birth > SKIN_TONE_COUNT) return 0;
    if (tone == TONE_NONE) return 0;                 // they had none: the revived villager is a newcomer
    return Bind(slot, tone, birth ? birth : (tone <= SKIN_TONE_COUNT ? tone : 0), 0) != 0;
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
    for (unsigned i = 0; i < sizeof(SKIN_PINS) / sizeof(SKIN_PINS[0]); ++i) {
        const SkinPin &p = SKIN_PINS[i];
        if (p.va < 0x401000u || p.va + p.len > end) return false;
        const unsigned char *live = (const unsigned char *)p.va;
        for (unsigned k = 0; k < p.len; ++k)
            if (!p.mask[k] && live[k] != p.bytes[k]) return false;
    }
    return true;
}

static void *const EntryHandlers[4] = { (void *)&BlitHook, (void *)&DrawVillagerHook, (void *)&PortraitHook,
                                        (void *)&EventPortraitHook };
static void *const CallHandlers[8] = { (void *)&Carried1Hook, (void *)&Carried2Hook, (void *)&TreeParent1Hook,
                                       (void *)&TreeParent2Hook, (void *)&TreeChildHook, (void *)&ConceptionWrapper,
                                       (void *)&ChangeName1Hook, (void *)&ChangeName2Hook };

struct Write { unsigned va, len; unsigned char bytes[8], original[8]; };
struct Plan { Write writes[12]; unsigned count; unsigned load, save; };

static bool PlanHooks(Plan &plan) {
    plan.count = 0;
    unsigned char *t = Trampolines;
    for (unsigned i = 0; i < 4; ++i) {
        const SkinEntryHook &h = SKIN_ENTRY_HOOKS[i];
        Write &w = plan.writes[plan.count++];
        w.va = h.va;
        w.len = h.stolen;
        w.bytes[0] = 0xE9;
        *(int *)(w.bytes + 1) = (int)((unsigned)EntryHandlers[i] - (h.va + 5));
        for (unsigned k = 5; k < h.stolen; ++k) w.bytes[k] = 0x90;
        EntryNext[i] = t;
        Copy(t, (const void *)h.va, h.stolen);      // whole, position-independent instructions (vf1_skin_sites.py)
        t[h.stolen] = 0xE9;
        *(int *)(t + h.stolen + 1) = (int)((h.va + h.stolen) - ((unsigned)t + h.stolen + 5));
        t += 16;
    }
    for (unsigned i = 0; i < 8; ++i) {
        const SkinCallHook &h = SKIN_CALL_HOOKS[i];
        if (*(const unsigned char *)h.site != 0xE8) return false;
        unsigned now = JumpTarget(h.site);
        if (now != h.target && InExe(now)) return false;       // the stock function, or a companion's wrapper of it
        CallNext[i] = (void *)now;
        Write &w = plan.writes[plan.count++];
        w.va = h.site;
        w.len = 5;
        w.bytes[0] = 0xE8;
        *(int *)(w.bytes + 1) = (int)((unsigned)CallHandlers[i] - (h.site + 5));
    }
    unsigned load = *(const unsigned *)SKIN_GS_VTABLE_LOAD, save = *(const unsigned *)SKIN_GS_VTABLE_SAVE;
    if ((load != SKIN_FN_GS_LOAD && InExe(load)) || (save != SKIN_FN_GS_SAVE && InExe(save))) return false;
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
        Write &w = plan.writes[done];
        Copy(w.original, (const void *)w.va, w.len);
        if (!WriteCode(w.va, w.bytes, w.len)) break;
    }
    NextLoad = (GameStateSlotFn)plan.load;
    NextSave = (GameStateSlotFn)plan.save;
    bool ok = done == plan.count && WriteSlot(SKIN_GS_VTABLE_LOAD, (unsigned)&GameStateLoad);
    if (ok && !WriteSlot(SKIN_GS_VTABLE_SAVE, (unsigned)&GameStateSave)) {
        WriteSlot(SKIN_GS_VTABLE_LOAD, plan.load);
        ok = false;
    }
    if (!ok) {
        for (unsigned j = 0; j < done; ++j) WriteCode(plan.writes[j].va, plan.writes[j].original, plan.writes[j].len);
        return false;
    }
    return true;
}

static bool SettingOn() {
    wchar_t path[MAX_PATH];
    Append(path, MAX_PATH, Folder, L"settings.ini");
    return GetPrivateProfileIntW(L"Patches", L"SkinTones", 0, path) == 1;
}

static int PreferredSetting() {
    wchar_t path[MAX_PATH];
    Append(path, MAX_PATH, Folder, L"settings.ini");
    const unsigned tone = GetPrivateProfileIntW(L"SkinTones", L"PreferredTone", 0, path);
    return tone >= 1 && tone <= SKIN_TONE_COUNT ? (int)tone : 0;
}

extern "C" __declspec(dllexport) int __cdecl VF1Skin_Startup() {
    static bool started = false;
    if (started) return (int)VF1Skin_Status.installed;
    started = true;
    HMODULE self = 0;              // this DLL, from one of its own addresses (whoever loaded it, however)
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCWSTR)&VF1Skin_Status, &self))
        self = ThisModule;
    DWORD n = GetModuleFileNameW(self, Folder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    while (n && Folder[n - 1] != L'\\') --n;
    if (!n) return 0;
    Folder[n] = 0;
    n = GetModuleFileNameW(0, GameFolder, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return 0;
    while (n && GameFolder[n - 1] != L'\\') --n;
    if (!n) return 0;
    GameFolder[n] = 0;
    bool on = SettingOn();
    VF1Skin_Status.requested = on ? 1u : 0u;
    if (!on) return 0;
    PreferredTone = PreferredSetting();
    VF1Skin_Status.preferred = (unsigned)PreferredTone;
    if (!PinsMatch()) { Log("the executable could not be proved: installing nothing"); return 0; }
    HMODULE sdl = GetModuleHandleW(L"SDL2.dll");
    if (sdl) {
        CreateSurface = (CreateSurfaceFn)GetProcAddress(sdl, "SDL_CreateRGBSurface");
        FreeSurface = (FreeSurfaceFn)GetProcAddress(sdl, "SDL_FreeSurface");
    }
    if (!CreateSurface || !FreeSurface) { Log("SDL2.dll is not as expected: installing nothing"); return 0; }
    DWORD old = 0;
    if (!VirtualProtect(Trampolines, sizeof Trampolines, PAGE_EXECUTE_READWRITE, &old)) return 0;
    static Plan plan;
    if (!PlanHooks(plan)) { Log("a hooked site is not as expected: installing nothing"); return 0; }
    FlushInstructionCache(GetCurrentProcess(), Trampolines, sizeof Trampolines);
    VF1Skin_Status.resolved = 1;
    Seed();
    ClearEntries();
    if (Apply(plan)) {
        VF1Skin_Status.installed = 1;
        Log("Skin Tones installed");
    }
    return (int)VF1Skin_Status.installed;
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}
