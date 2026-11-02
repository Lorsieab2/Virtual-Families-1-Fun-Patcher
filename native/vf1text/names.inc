// ---------------------------------------------------------------- one character limit for every name box
// (included by vf1text.cpp; patcher/vf1_names.py is the same rule in the patcher, tests/test_name_limit.py proves both)
//
// Every name box of the game takes VF1_NAME_LETTERS characters (300, patcher/vf1_text.py NAME_LETTERS), with its
// buffer at VF1_NAME_BOX_BYTES (1,200 bytes, the engine's own cap in SetEditable 0x40D3B3: never patched past).
// The boxes (SetEditable 0x40D6F0 -> 0x40D370 called from):
//   0x41BB4F 0x41BBEF 0x41BC91 0x41BD36 0x41BDF0 0x41BF15  the slot menu's five name boxes (and New Player's),
//   0x41C67C  the first family's name,   0x435AFB  adoption,   0x437955  a new baby,   0x44A6DE  renaming a member.
// Not names, left as they are: 0x4172A8 (an 80-byte field of a Job / Likes dialog), 0x43F1B0 / 0x43F200 (the
// animation tool, 20 and 31 bytes).
//
// The save keeps every name in its own fixed field, so what the game stores is never more than before: GetText
// (0x40D740) gives the game the SHORT FORM of a longer name (patcher/vf1_names.py short_form: the longest start that
// fits + "...", or "2...", "3..." when taken; unique in the save, so it follows the family member), and the whole
// name goes to the save's Names file, "<saves>\Virtual Families 1 Patcher Data\Names\Virtual Families<N>.ldw.txt".
// Wherever a short form is drawn or measured (DrawString, GetWidth, the word wrapper 0x409D70) the whole name is
// drawn instead, fitted with an ellipsis into the room the stock game leaves for that field: the width of as many
// "W" as the field holds bytes. A box shows the end of a long name while it is typed into (0x40D140 would cut the
// text to the box's width otherwise) and starts with the whole name when it opens with a short form.
//
// Names that fit their field but not their spot on the screen (a 5-sign Cuneiform name is 20 bytes of a 24-byte
// field, but wider than a child's frame on the Family Tree screen): every fixed spot where the game draws a name has
// its real room below (NameSpots, by the return address of the draw or of the SetText that puts the name there), and
// a name wider than it is drawn as its start, cut between whole characters, with "…" (FitToRoom). A name that fits is
// drawn exactly as before. docs/UNICODE_TEXT.md, "Names fitted to their spot", has each spot and how its room was found.

#include <intrin.h>
#pragma intrinsic(_ReturnAddress)

static const unsigned GameStateInstance = 0x50025C;      // theGameState*
static const unsigned GsCurrentSlot = 0x1B188;            // the slot being played, 1..5
static const unsigned MakePathVSlot = 0xC;                // ldwGameState vtable: the save file of a slot (0x4035F0)
typedef const char *(__thiscall *MakePathFn)(void *state, int slot);
typedef int (__thiscall *GameGetWidthFn)(void *font, const char *text, float scale);
static const GameGetWidthFn GameGetWidth = (GameGetWidthFn)0x402320;

static const int MarkLen = sizeof(VF1_NAME_MARK) - 1;

// ---- where each GetText goes: the slot whose Names file it is (fixed for the slot menu's boxes and the first
// family, the slot being played for a member's name), or 0 for a GetText that only reads a box.
struct NameSite { unsigned ret; int slot; };
static const NameSite NameSites[] = {
    { 0x41C730, 1 },                                   // the first family (0x41C755 then makes it slot 1)
    { 0x41C1C0, 1 }, { 0x41C20C, 2 }, { 0x41C25C, 3 }, { 0x41C2AC, 4 }, { 0x41C2F9, 5 },   // New Player in slot k
    { 0x43682F, -1 }, { 0x4382A2, -1 }, { 0x44BCE6, -1 }, { 0x44BDE3, -1 },               // a member's name
};
static const unsigned NameBoxCalls[] = {          // return addresses of SetEditable calls that set up a name box
    0x41BB54, 0x41BBF4, 0x41BC96, 0x41BD3B, 0x41BDF5, 0x41BF1A, 0x41C681, 0x435B00, 0x43795A, 0x44A6E3,
};

// ---- the Names files
struct NameEntry {
    NameEntry *next;
    char *shortForm; int shortLen;
    int room;
    char *full; int fullLen;
    void *fitImpl[8]; char *fit[8];                   // the whole name fitted to its room, per font
};
struct NameBook { bool loaded; NameEntry *first, *last; };
static NameBook Books[6];                             // 1..5
extern "C" __declspec(dllexport) volatile unsigned VF1Text_NamesWritten = 0;   // for the tests
extern "C" __declspec(dllexport) volatile unsigned VF1Text_NamesFailed = 0;

static int CurrentSlot() {
    unsigned char *gs = *(unsigned char **)GameStateInstance;
    if (!gs) return 0;
    int s = *(int *)(gs + GsCurrentSlot);
    return (s >= 1 && s <= 5) ? s : 0;
}

// "<folder>\Virtual Families 1 Patcher Data\Names\<save file>.txt", and the two folders.
static bool NamesPath(int slot, char *out, unsigned cap, char *data, char *names) {
    void *gs = *(void **)GameStateInstance;
    if (!gs) return false;
    void **vtable = *(void ***)gs;
    const char *save = ((MakePathFn)vtable[MakePathVSlot / 4])(gs, slot);
    if (!save) return false;
    unsigned n = Len(save);
    unsigned cut = n;
    while (cut > 0 && save[cut - 1] != '\\' && save[cut - 1] != '/') --cut;
    if (cut == 0 || cut == n) return false;
    static const char d[] = "Virtual Families 1 Patcher Data", m[] = "\\Names\\";
    unsigned dl = sizeof d - 1, ml = sizeof m - 1;
    if (n + dl + ml + 5 >= cap) return false;
    Copy(out, save, cut);
    Copy(out + cut, d, dl);
    Copy(data, out, cut + dl); data[cut + dl] = 0;
    Copy(out + cut + dl, m, ml);
    Copy(names, out, cut + dl + ml - 1); names[cut + dl + ml - 1] = 0;
    Copy(out + cut + dl + ml, save + cut, n - cut);
    Copy(out + cut + dl + ml + (n - cut), ".txt", 5);
    return true;
}

static int ClusterCount(const unsigned char *s, int n) {
    Run run;
    if (!DecodeRun(&run, (const char *)s, n, 1)) return 0x7FFFFFFF;
    int count = 0;
    for (int i = 0; i < run.n; ++count) i = ClusterEnd(run.cps, run.n, i);
    FreeRun(&run);
    return count;
}

// patcher/vf1_names.name_problem: 1..300 characters, at most 1,200 bytes, valid UTF-8, no control characters.
static bool GoodName(const unsigned char *s, int n) {
    if (n <= 0 || n > VF1_NAME_BOX_BYTES || !IsUtf8(s, n)) return false;
    for (int i = 0; i < n;) {
        unsigned cp;
        int k = Utf8At(s + i, n - i, &cp);
        if (cp < 0x20 || (cp >= 0x7F && cp < 0xA0)) return false;
        i += k;
    }
    return ClusterCount(s, n) <= VF1_NAME_LETTERS;
}

static char *Dup(const char *s, int n) {
    char *p = (char *)Alloc((unsigned)n + 1);
    if (p) { Copy(p, s, (unsigned)n); p[n] = 0; }
    return p;
}

static NameEntry *FindShort(const char *s, int n, int slot) {      // slot 0: every book
    for (int b = 1; b <= 5; ++b) {
        if (slot && b != slot) continue;
        for (NameEntry *e = Books[b].first; e; e = e->next)
            if (e->shortLen == n && Same(e->shortForm, s, (unsigned)n)) return e;
    }
    return 0;
}

static bool AddEntry(int slot, const char *s, int sn, int room, const char *full, int fn) {
    NameEntry *e = (NameEntry *)Alloc(sizeof(NameEntry));
    if (!e) return false;
    e->shortForm = Dup(s, sn); e->shortLen = sn; e->room = room;
    e->full = Dup(full, fn); e->fullLen = fn;
    if (!e->shortForm || !e->full) return false;
    if (Books[slot].last) Books[slot].last->next = e; else Books[slot].first = e;
    Books[slot].last = e;
    return true;
}

static const char NamesHeader[] = "VF1 Names 1";

static void LoadBook(int slot) {
    NameBook &book = Books[slot];
    if (book.loaded) return;
    char path[MAX_PATH + 96], data[MAX_PATH + 96], names[MAX_PATH + 96];
    if (!NamesPath(slot, path, sizeof path, data, names)) return;     // no game state yet: try again later
    book.loaded = true;
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD size = GetFileSize(h, 0);
    if (size == INVALID_FILE_SIZE || size > (8u << 20)) { CloseHandle(h); return; }
    char *buf = (char *)Alloc(size + 1);
    DWORD got = 0;
    BOOL ok = buf ? ReadFile(h, buf, size, &got, 0) : FALSE;
    CloseHandle(h);
    if (!ok || got != size) { Free(buf); return; }
    // the header line, then "short<TAB>room<TAB>name" lines (vf1_names.parse: anything not valid is left out)
    unsigned at = 0, hl = sizeof NamesHeader - 1;
    unsigned end0 = 0;
    while (end0 < size && buf[end0] != '\n') ++end0;
    unsigned hlen = (end0 > 0 && buf[end0 - 1] == '\r') ? end0 - 1 : end0;
    if (hlen != hl || !Same(buf, NamesHeader, hl)) { Free(buf); return; }
    at = end0 + 1;
    while (at < size) {
        unsigned end = at;
        while (end < size && buf[end] != '\n') ++end;
        unsigned len = end - at;
        if (len && buf[at + len - 1] == '\r') --len;
        char *line = buf + at;
        int tab1 = -1, tab2 = -1, tabs = 0;
        for (unsigned i = 0; i < len; ++i)
            if (line[i] == '\t') { ++tabs; if (tab1 < 0) tab1 = (int)i; else if (tab2 < 0) tab2 = (int)i; }
        if (tabs == 2 && tab2 > tab1 + 1) {
            int room = 0;
            bool digits = true;
            for (int i = tab1 + 1; i < tab2; ++i) {
                if (line[i] < '0' || line[i] > '9' || room > 100000) { digits = false; break; }
                room = room * 10 + (line[i] - '0');
            }
            const char *s = line; int sn = tab1;
            const char *full = line + tab2 + 1; int fn = (int)len - tab2 - 1;
            if (digits && room >= 1 && room < VF1_NAME_BOX_BYTES && sn >= MarkLen && sn <= room &&
                Same(s + sn - MarkLen, VF1_NAME_MARK, (unsigned)MarkLen) && GoodName((const unsigned char *)s, sn) &&
                GoodName((const unsigned char *)full, fn) && !FindShort(s, sn, slot))
                AddEntry(slot, s, sn, room, full, fn);
        }
        at = end + 1;
    }
    Free(buf);
}

static void LoadBooks() { for (int b = 1; b <= 5; ++b) LoadBook(b); }

static bool WriteBook(int slot) {
    char path[MAX_PATH + 96], data[MAX_PATH + 96], names[MAX_PATH + 96], temp[MAX_PATH + 104];
    if (!NamesPath(slot, path, sizeof path, data, names)) return false;
    unsigned total = sizeof NamesHeader + 1;
    for (NameEntry *e = Books[slot].first; e; e = e->next) total += (unsigned)(e->shortLen + e->fullLen) + 16;
    char *buf = (char *)Alloc(total);
    if (!buf) return false;
    unsigned n = 0;
    Copy(buf, NamesHeader, sizeof NamesHeader - 1); n += sizeof NamesHeader - 1;
    buf[n++] = '\n';
    for (NameEntry *e = Books[slot].first; e; e = e->next) {
        Copy(buf + n, e->shortForm, (unsigned)e->shortLen); n += (unsigned)e->shortLen;
        buf[n++] = '\t';
        char d[12]; int k = 0; int r = e->room;
        do { d[k++] = (char)('0' + r % 10); r /= 10; } while (r);
        while (k) buf[n++] = d[--k];
        buf[n++] = '\t';
        Copy(buf + n, e->full, (unsigned)e->fullLen); n += (unsigned)e->fullLen;
        buf[n++] = '\n';
    }
    CreateDirectoryA(data, 0);
    CreateDirectoryA(names, 0);
    unsigned pl = Len(path);
    Copy(temp, path, pl);
    Copy(temp + pl, ".tmp", 5);
    bool ok = false;
    HANDLE h = CreateFileA(temp, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h != INVALID_HANDLE_VALUE) {
        DWORD put = 0;
        BOOL w = WriteFile(h, buf, n, &put, 0);
        CloseHandle(h);
        ok = w && put == n && MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
        if (!ok) DeleteFileA(temp);
    }
    Free(buf);
    if (ok) ++VF1Text_NamesWritten; else ++VF1Text_NamesFailed;
    return ok;
}

// ---- the short form (vf1_names.short_form)
// `full` (n bytes) for a field of `room` bytes, into out (room + 1 bytes). slot 1..5 records a new short form in that
// slot's Names file; slot 0 only reuses one (a GetText that reads a box) and otherwise cuts as the stock game does.
static int ShortFor(const char *full, int n, int room, int slot, char *out) {
    LoadBooks();
    for (int b = 1; b <= 5; ++b)
        for (NameEntry *e = Books[b].first; e; e = e->next)
            if (e->fullLen == n && e->shortLen <= room && Same(e->full, full, (unsigned)n)) {
                Copy(out, e->shortForm, (unsigned)e->shortLen);
                out[e->shortLen] = 0;
                if (slot >= 1 && !FindShort(e->shortForm, e->shortLen, slot)) {
                    AddEntry(slot, e->shortForm, e->shortLen, e->room, e->full, e->fullLen);
                    WriteBook(slot);
                }
                return e->shortLen;
            }
    if (n <= room && !FindShort(full, n, 0)) {
        Copy(out, full, (unsigned)n); out[n] = 0;
        return n;
    }
    if (slot < 1 || !GoodName((const unsigned char *)full, n)) {
        int keep = FitBytes((const unsigned char *)full, n, room);
        Copy(out, full, (unsigned)keep); out[keep] = 0;
        return keep;
    }
    for (int k = 1; k < 100000; ++k) {
        char tail[16]; int tl = 0;
        if (k > 1) { char d[8]; int m = 0; int v = k; do { d[m++] = (char)('0' + v % 10); v /= 10; } while (v); while (m) tail[tl++] = d[--m]; }
        Copy(tail + tl, VF1_NAME_MARK, (unsigned)MarkLen); tl += MarkLen;
        if (tl > room) break;
        int head = FitBytes((const unsigned char *)full, n, room - tl);
        while (head > 0 && full[head - 1] == ' ') --head;
        Copy(out, full, (unsigned)head);
        Copy(out + head, tail, (unsigned)tl);
        int sn = head + tl;
        out[sn] = 0;
        if (!FindShort(out, sn, 0)) {
            if (AddEntry(slot, out, sn, room, full, n)) WriteBook(slot);
            return sn;
        }
    }
    int keep = FitBytes((const unsigned char *)full, n, room);
    Copy(out, full, (unsigned)keep); out[keep] = 0;
    return keep;
}

// The entry a drawn short form stands for: the slot being played first, then any slot (the slot menu's names).
static NameEntry *DisplayEntry(const char *s, int n) {
    int slot = CurrentSlot();
    NameEntry *e = slot ? FindShort(s, n, slot) : 0;
    return e ? e : FindShort(s, n, 0);
}

static bool AnyNames() {
    LoadBooks();
    for (int b = 1; b <= 5; ++b) if (Books[b].first) return true;
    return false;
}

// ---- drawing the whole name
static int MeasureRaw(void *impl, FontExtra *f, const char *text, int bytes);

static const char Ellipsis[] = "\xE2\x80\xA6";       // U+2026

static const char *FittedName(NameEntry *e, void *impl) {
    int slot = -1;
    for (int i = 0; i < 8; ++i) {
        if (e->fitImpl[i] == impl && e->fit[i]) return e->fit[i];
        if (!e->fitImpl[i] && slot < 0) slot = i;
    }
    FontExtra *f = ExtraFor(impl);
    char ws[VF1_NAME_BOX_BYTES + 1];
    int rw = e->room < VF1_NAME_BOX_BYTES ? e->room : VF1_NAME_BOX_BYTES;
    for (int i = 0; i < rw; ++i) ws[i] = 'W';
    int room = MeasureRaw(impl, f, ws, rw);
    char *out = 0;
    if (MeasureRaw(impl, f, e->full, e->fullLen) <= room) {
        out = e->full;
    } else {
        Run run;
        out = (char *)Alloc((unsigned)e->fullLen + 4);
        if (out && DecodeRun(&run, e->full, e->fullLen, 1)) {
            int bytes = 0, best = 0;
            for (int i = 0; i < run.n;) {
                int j = ClusterEnd(run.cps, run.n, i);
                int add = 0;
                for (int k = i; k < j; ++k) add += run.widths[k];
                Copy(out, e->full, (unsigned)(bytes + add));
                Copy(out + bytes + add, Ellipsis, 3);
                if (MeasureRaw(impl, f, out, bytes + add + 3) > room) break;
                bytes += add;
                best = bytes;
                i = j;
            }
            FreeRun(&run);
            while (best > 0 && e->full[best - 1] == ' ') --best;
            Copy(out, e->full, (unsigned)best);
            Copy(out + best, Ellipsis, 4);              // with its NUL
        } else if (out) {
            Free(out);
            out = e->shortForm;
        } else {
            out = e->shortForm;
        }
    }
    if (slot >= 0) { e->fitImpl[slot] = impl; e->fit[slot] = out; }
    return out;
}

// `text` with every short form in it replaced by its fitted whole name; the text itself when there is none. A
// replaced text is on the heap and *owned is set (FreeNames frees it). Every short form ends with the mark, so only
// the places where "..." ends are looked at.
static const char *WithNames(const char *text, void *impl, char **owned) {
    *owned = 0;
    if (!text || !impl) return text;
    int n = (int)Len(text);
    bool mark = false;
    for (int i = 0; i + MarkLen <= n; ++i)
        if (Same(text + i, VF1_NAME_MARK, (unsigned)MarkLen)) { mark = true; break; }
    if (!mark || !IsUtf8((const unsigned char *)text, n) || !AnyNames()) return text;
    // first pass: the replacements, left to right, the longest short form ending at each mark
    struct Hit { int at, len; const char *with; };
    Hit hits[32];
    int count = 0, done = 0;
    for (int i = MarkLen; i <= n && count < 32; ++i) {
        if (!Same(text + i - MarkLen, VF1_NAME_MARK, (unsigned)MarkLen)) continue;
        NameEntry *best = 0;
        int bestLen = 0;
        for (int b = 1; b <= 5; ++b)
            for (NameEntry *e = Books[b].first; e; e = e->next)
                if (e->shortLen <= i - done && e->shortLen > bestLen &&
                    Same(text + i - e->shortLen, e->shortForm, (unsigned)e->shortLen)) {
                    NameEntry *d = DisplayEntry(e->shortForm, e->shortLen);
                    best = d ? d : e;
                    bestLen = e->shortLen;
                }
        if (!best) continue;
        hits[count].at = i - bestLen; hits[count].len = bestLen; hits[count].with = FittedName(best, impl);
        ++count;
        done = i;
    }
    if (!count) return text;
    int total = n + 1;
    for (int k = 0; k < count; ++k) total += (int)Len(hits[k].with) - hits[k].len;
    char *out = (char *)Alloc((unsigned)total);
    if (!out) return text;
    int at = 0, o = 0;
    for (int k = 0; k < count; ++k) {
        Copy(out + o, text + at, (unsigned)(hits[k].at - at)); o += hits[k].at - at;
        int wl = (int)Len(hits[k].with);
        Copy(out + o, hits[k].with, (unsigned)wl); o += wl;
        at = hits[k].at + hits[k].len;
    }
    Copy(out + o, text + at, (unsigned)(n - at)); o += n - at;
    out[o] = 0;
    *owned = out;
    return out;
}

// ---- names fitted to their spot on the screen
// A spot: the return address of the game's call that draws a name there (DrawString 0x409CC0 -> 0x409660, or the
// centred draw 0x409D20) or that puts the name in a label (ldwTextControl::SetText 0x40D700 -> 0x40D430), and the
// widest the name may be drawn there, in pixels. RoomIsBox: the label's own width (its rectangle, 0x40D140's test).
// Found in the vanilla exe (1.01.00) and its layouts emulated (tests/test_name_fit.py runs each one):
static const int RoomIsBox = -1;
struct NameSpot { unsigned ret; int room; };
static const NameSpot DrawSpots[] = {
    // The Family Tree screen's family row 0x439BA0 (layout: the screen's constructor 0x438AB5..0x438BFE, rows drawn
    // inside the clip 34, 142 .. 736, 600). Each parent's name is drawn left-aligned at the portrait's right + 4
    // (0x439C65 / 0x439DA5: x = row + [screen+0x70] + 4 = 147) inside the parent frame familytree_parentframe.png
    // (248 x 91, drawn at row + [screen+0x68] - 8 = 26, 0x439C2E / 0x439D7F): its right edge is at 274, so 127.
    { 0x439C79, 127 },                                   // the first parent (record +4), 0x439C74
    { 0x439DB8, 127 },                                   // the second parent (record +0xDC), 0x439DB3
    // Each child's name is centred (0x409D20: x = centre - width / 2) 46 pixels right of its frame's left edge
    // (frame at 0x439F01, centre at 0x439F3B), familytree_childframe.png 94 x 74: a name of 93 pixels or less lies
    // inside the frame (46 to its left, 47 to its right), so 93.
    { 0x439F4E, 93 },                                    // each child (record +0x1B8 + 0xD8 k), 0x439F49
};
static const NameSpot LabelSpots[] = {
    // The house screen's bottom bar (made by 0x444600..0x444C40): the selected person's name, a left-aligned label at
    // (61, 538) made for "Joey Joerson" (0x4446D3); the label is not editable, so the stock draw never cuts it (the
    // cut at 0x40D2B7 is only for editable boxes) and a wider name runs on under the "Age" column, whose caption
    // starts at x = 202 (0x444772). So 202 - 61 = 141.
    { 0x445715, 141 },                                   // SetText(sprintf("%s", name)) at 0x445710
    // The same bar's status line ("{name} sees {name2}.", 0x44E9B0's messages): a label centred in a box made for
    // 26 "W" (0x444BDF: 187 .. 603), never cut by the stock draw; its box is its room.
    { 0x44586B, RoomIsBox },                             // SetText(the message) at 0x445866
};

// The label rooms in force: a label whose text was last set from a LabelSpot.
struct LabelRoom { void *impl; int room; };
static LabelRoom LabelRooms[16];

static void NoteLabel(void *impl, unsigned ret) {
    int room = 0;
    bool spot = false;
    for (unsigned i = 0; i < sizeof LabelSpots / sizeof LabelSpots[0]; ++i)
        if (LabelSpots[i].ret == ret) { room = LabelSpots[i].room; spot = true; }
    int free = -1;
    for (int i = 0; i < 16; ++i) {
        if (LabelRooms[i].impl == impl) { LabelRooms[i].impl = 0; if (free < 0) free = i; }
        else if (!LabelRooms[i].impl && free < 0) free = i;
    }
    if (spot && free >= 0) { LabelRooms[free].impl = impl; LabelRooms[free].room = room; }
}

static bool LabelSpotRoom(void *impl, int *room) {
    for (int i = 0; i < 16; ++i)
        if (LabelRooms[i].impl == impl) { *room = LabelRooms[i].room; return true; }
    return false;
}

// The game's call site a DrawString (0x409660) or GetWidth (0x402320) hook was reached from: its own return address,
// or, from inside the right-aligned (0x409CD0) and centred (0x409D20) draws, theirs. Both push ebx, esi and edi
// before measuring (GetWidth's return 0x409CF6 / 0x409D46: the caller's return 6 dwords up) and drawing
// (DrawString's return 0x409D10 / 0x409D67: 9 dwords up). `slot` is the hook's own return address slot.
static unsigned GameSite(void *slot) {
    unsigned *s = (unsigned *)slot;
    switch (s[0]) {
    case 0x409CF6: case 0x409D46: return s[6];
    case 0x409D10: case 0x409D67: return s[9];
    default: return s[0];
    }
}

static int DrawSpotRoom(unsigned site) {
    for (unsigned i = 0; i < sizeof DrawSpots / sizeof DrawSpots[0]; ++i)
        if (DrawSpots[i].ret == site) return DrawSpots[i].room;
    return -1;
}

// One whole character's advance as Measure counts it (scale 1): its box width plus the font's spacing.
static int Advance(void *impl, FontExtra *f, const unsigned *cps, int i, int j) {
    Letter l = LetterFor(f, impl, cps, i, j);
    ldwRect r;
    LetterBox(impl, l, &r);
    return *(int *)((char *)impl + 8) + r.right - r.left;
}

// `text` fitted into `room` pixels of this font: the text itself when it is no wider (one line); else its longest
// start of whole characters (grapheme clusters), trailing spaces dropped, then "…" (U+2026; in a text read one byte
// per character, the Windows-1252 byte 0x85, the same letter), on the heap (*owned). Nothing at all when not even "…"
// fits.
static const char *FitToRoom(const char *text, void *impl, int room, char **owned) {
    *owned = 0;
    if (!text || !impl || room < 0) return text;
    FontExtra *f = ExtraFor(impl);
    int n = (int)Len(text);
    for (int i = 0; i < n; ++i) if (text[i] == '\n') return text;     // names are one line
    if (MeasureRaw(impl, f, text, n) <= room) return text;
    bool utf8 = IsUtf8((const unsigned char *)text, n);
    Run run;
    if (!DecodeRun(&run, text, n, utf8 ? 1 : 0)) return text;
    unsigned ell[2] = { 0x2026, 0 };
    int spacing = *(int *)((char *)impl + 8);
    int ellipsis = Advance(impl, f, ell, 0, 1);
    char *out = (char *)Alloc((unsigned)n + 4);
    if (!out) { FreeRun(&run); return text; }
    // width: the advances of the start taken so far (trailing spaces too: they are dropped from what is kept, but a
    // letter after them needs their room); keep: its bytes up to its last letter that is not a space
    int width = 0, bytes = 0, keep = 0;
    bool any = ellipsis - spacing <= room;
    for (int i = 0; i < run.n && any;) {
        int j = ClusterEnd(run.cps, run.n, i);
        int add = 0;
        for (int k = i; k < j; ++k) add += run.widths[k];
        int w = width + Advance(impl, f, run.cps, i, j);
        bool space = j == i + 1 && run.cps[i] == ' ';
        if (!space && w + ellipsis - spacing > room) break;
        width = w;
        bytes += add;
        if (!space) keep = bytes;
        i = j;
    }
    FreeRun(&run);
    if (!any) { out[0] = 0; *owned = out; return out; }
    Copy(out, text, (unsigned)keep);
    if (utf8) { Copy(out + keep, Ellipsis, 4); }
    else { ((unsigned char *)out)[keep] = 0x85; out[keep + 1] = 0; }
    *owned = out;
    return out;
}

// What a draw or measure from `site` shows: whole names for short forms (WithNames), then fitted to the spot.
static const char *NamesAt(const char *text, void *impl, unsigned site, char **owned) {
    char *whole;
    const char *shown = WithNames(text, impl, &whole);
    int room = DrawSpotRoom(site);
    if (room < 0) { *owned = whole; return shown; }
    char *fit;
    const char *out = FitToRoom(shown, impl, room, &fit);
    if (fit) { Free(whole); *owned = fit; return out; }
    *owned = whole;
    return shown;
}

// ---- the name boxes
// A name box: editable (+0x24, set by SetEditable), its limit the name boxes' VF1_NAME_BOX_BYTES, not numbers-only.
// Editable matters: the text control's constructor 0x40D7E0 starts every control, labels too, with the limit 0x4B0
// (0x40D851), so the limit alone would take every label for a name box (and draw it cut to the size it was made for:
// the bottom bar's name to "Joey Joerson", a label made for "." to nothing).
static bool IsNameBox(TextControl *c) {
    return TC_B(c, 0x24) && TC_I(c, 0x28) == VF1_NAME_BOX_BYTES && !TC_B(c, 0x2D);
}

// A box that opens with a short form opens with the whole name (its buffer holds VF1_NAME_BOX_BYTES + 1 bytes).
static void OpenWithWholeName(TextControl *c) {
    if (!IsNameBox(c) || TC_B(c, 0x2F)) return;
    char *buf = TC_P(c, 0x30);
    if (!buf) return;
    int n = (int)Len(buf);
    if (n < MarkLen || !Same(buf + n - MarkLen, VF1_NAME_MARK, (unsigned)MarkLen)) return;
    LoadBooks();
    NameEntry *e = DisplayEntry(buf, n);
    if (!e || e->fullLen > VF1_NAME_BOX_BYTES) return;
    Copy(buf, e->full, (unsigned)e->fullLen);
    buf[e->fullLen] = 0;
}

typedef void (__thiscall *SetEditableFn)(void *impl, bool editable, int limit);
typedef void (__thiscall *SetTextFn)(void *impl, const char *text);
typedef void (__thiscall *BoxDrawFn)(void *impl);
typedef int (__thiscall *WrapFn)(void *window, const char *text, int a1, int a2, int a3, int a4, void *font, int a6);

// the first instructions of each hooked function, then on into it
__declspec(naked) static void SetEditableStock() { __asm { push ebx
                                                            mov bl, byte ptr [esp + 8]
                                                            push 0x40D375
                                                            ret } }
__declspec(naked) static void SetTextStock() { __asm { push esi
                                                        mov esi, ecx
                                                        mov eax, dword ptr [esi + 0x30]
                                                        push 0x40D436
                                                        ret } }
__declspec(naked) static void BoxDrawStock() { __asm { sub esp, 0x34
                                                        push esi
                                                        mov esi, ecx
                                                        push 0x40D146
                                                        ret } }
__declspec(naked) static void WrapStock() { __asm { sub esp, 0x4DC
                                                     push 0x409D76
                                                     ret } }

// 0x40D370 ldwTextControlImpl::SetEditable(editable, limit), ret 8: a name box's limit is VF1_NAME_BOX_BYTES.
static void __fastcall SetEditableHook(TextControl *c, void *, bool editable, int limit) {
    unsigned ret = (unsigned)(UINT_PTR)_ReturnAddress();
    if (editable)
        for (unsigned i = 0; i < sizeof NameBoxCalls / sizeof NameBoxCalls[0]; ++i)
            if (NameBoxCalls[i] == ret) { limit = VF1_NAME_BOX_BYTES; break; }
    ((SetEditableFn)(void *)&SetEditableStock)(c, editable, limit);
    OpenWithWholeName(c);
}

// 0x40D430 ldwTextControlImpl::SetText(text), ret 4.
// Called through ldwTextControl::SetText 0x40D700 (mov ecx, [ecx+0x10]; jmp), so the return address is the game's
// call site: a label given a name at a LabelSpot draws it fitted to that spot's room.
static void __fastcall SetTextHook(TextControl *c, void *, const char *text) {
    NoteLabel(c, (unsigned)(UINT_PTR)_ReturnAddress());
    ((SetTextFn)(void *)&SetTextStock)(c, text);
    if (TC_B(c, 0x24)) OpenWithWholeName(c);
}

// The stock box draw's own test (0x40D20C..0x40D2B5): does `text` fit, or would the stock draw cut it?
static bool BoxFits(TextControl *c, void *font, const char *text) {
    int w = text[0] ? GameGetWidth(font, text, *(float *)(c->raw + 0x58)) : 0;
    int x;
    switch (TC_I(c, 0x40)) {
    case 0: x = TC_I(c, 0x44) + TC_I(c, 8); break;
    case 1: x = (TC_I(c, 0x10) - w - TC_I(c, 8)) / 2 + TC_I(c, 8); break;
    case 2: x = TC_I(c, 0x10) - TC_I(c, 0x44) - w; break;
    default: return true;
    }
    return x + w <= TC_I(c, 0x10);
}

// 0x40D140 ldwTextControlImpl::Draw. For a name box: the text as drawn (whole names), and when it is wider than the
// box, the end of it while it is typed into, else its start with an ellipsis; drawn from a copy, so the stock draw
// never cuts the box's own text (it deletes bytes from the end until the text fits, 0x40D2B7).
// The room a box leaves its text by the stock draw's own test (BoxFits): its width, less the inset when the text is
// not centred.
static int BoxRoom(TextControl *c) {
    int room = TC_I(c, 0x10) - TC_I(c, 8);
    if (TC_I(c, 0x40) != 1) room -= TC_I(c, 0x44);
    return room;
}

// A label at a LabelSpot (never editable: the stock draw does not cut it): its text as drawn (whole names), fitted to
// the spot's room, drawn from a copy.
static bool DrawLabelSpot(TextControl *c) {
    int room;
    char *buf = TC_P(c, 0x30);
    if (TC_B(c, 0x24) || TC_B(c, 0x2F) || !buf || !buf[0] || !TC_B(c, 0x2C) || !LabelSpotRoom(c, &room)) return false;
    void *font = *(void **)(c->raw + 0x3C);
    if (!font) {
        void *window = *(void **)0x500668;
        font = window ? *(void **)((char *)*(void **)window + 0x5C) : 0;
    }
    if (!font) return false;
    if (room == RoomIsBox) room = BoxRoom(c);
    char *whole, *fit;
    const char *shown = WithNames(buf, ImplOf(font), &whole);
    const char *out = FitToRoom(shown, ImplOf(font), room, &fit);
    if (!fit) { Free(whole); return false; }       // it fits: the stock draw, as before
    TC_P(c, 0x30) = (char *)out;
    ((BoxDrawFn)(void *)&BoxDrawStock)(c);
    TC_P(c, 0x30) = buf;
    Free(fit);
    Free(whole);
    return true;
}

static void __fastcall BoxDrawHook(TextControl *c, void *) {
    char *buf = TC_P(c, 0x30);
    if (!IsNameBox(c) && DrawLabelSpot(c)) return;
    if (!IsNameBox(c) || TC_B(c, 0x2F) || !buf || !buf[0] || !TC_B(c, 0x2C)) {
        ((BoxDrawFn)(void *)&BoxDrawStock)(c);
        return;
    }
    void *font = *(void **)(c->raw + 0x3C);
    if (!font) {
        void *window = *(void **)0x500668;               // 0x4080B0, then 0x408400
        font = window ? *(void **)((char *)*(void **)window + 0x5C) : 0;
    }
    if (!font) { ((BoxDrawFn)(void *)&BoxDrawStock)(c); return; }
    char *owned;
    const char *shown = WithNames(buf, ImplOf(font), &owned);
    if (BoxFits(c, font, shown)) {
        if (!owned) { ((BoxDrawFn)(void *)&BoxDrawStock)(c); return; }
    }
    int n = (int)Len(shown);
    char *copy = (char *)Alloc((unsigned)n + 8);
    if (!copy) { Free(owned); return; }               // never let the stock draw cut the box's text
    Run run;
    if (BoxFits(c, font, shown)) {
        Copy(copy, shown, (unsigned)n + 1);
    } else if (!DecodeRun(&run, shown, n, IsUtf8((const unsigned char *)shown, n) ? 1 : 0)) {
        copy[0] = 0;
    } else {
        // cluster starts, in bytes
        int *starts = (int *)Alloc(sizeof(int) * (unsigned)(run.n + 1));
        int count = 0, at = 0;
        if (starts) {
            for (int i = 0; i < run.n;) {
                int j = ClusterEnd(run.cps, run.n, i);
                starts[count++] = at;
                for (int k = i; k < j; ++k) at += run.widths[k];
                i = j;
            }
            starts[count] = at;
        }
        copy[0] = 0;
        if (starts && TC_B(c, 0x25)) {                // typed into: the end that fits
            for (int k = count - 1; k >= 0; --k) {
                char *tail = (char *)shown + starts[k];
                if (!BoxFits(c, font, tail)) break;
                Copy(copy, tail, (unsigned)(n - starts[k]) + 1);
            }
        } else if (starts) {                          // else the start, with an ellipsis
            for (int k = 1; k <= count; ++k) {
                int b = starts[k];
                Copy(copy, shown, (unsigned)b);
                Copy(copy + b, Ellipsis, 4);
                if (!BoxFits(c, font, copy)) {
                    b = starts[k - 1];
                    Copy(copy + b, Ellipsis, 4);
                    if (k == 1) copy[0] = 0;
                    break;
                }
            }
        }
        Free(starts);
        FreeRun(&run);
    }
    TC_P(c, 0x30) = copy;
    ((BoxDrawFn)(void *)&BoxDrawStock)(c);
    TC_P(c, 0x30) = buf;
    Free(copy);
    Free(owned);
}

// 0x409D70 the justified word wrapper (text, x, y, width, colour, font, measure only), ret 0x1C: whole names first.
static int __fastcall WrapHook(void *window, void *, const char *text, int a1, int a2, int a3, int a4, void *font,
                               int a6) {
    void *f = font ? font : *(void **)((char *)*(void **)window + 0x5C);
    char *owned = 0;
    const char *shown = f ? WithNames(text, ImplOf(f), &owned) : text;
    int r = ((WrapFn)(void *)&WrapStock)(window, shown, a1, a2, a3, a4, font, a6);
    Free(owned);
    return r;
}

// For vf1logs.dll (the Family History log) and vf1fun.dll's windows: the whole name a stored name stands for (the
// slot being played first), or the name itself.
extern "C" __declspec(dllexport) const char *__cdecl VF1Text_FullName(const char *stored) {
    if (!stored) return stored;
    int n = (int)Len(stored);
    if (n < MarkLen || !Same(stored + n - MarkLen, VF1_NAME_MARK, (unsigned)MarkLen)) return stored;
    LoadBooks();
    NameEntry *e = DisplayEntry(stored, n);
    return e ? e->full : stored;
}

// For vf1fun.dll's windows: what a member's field of `room` bytes stores for the typed name `full` (UTF-8) in the
// slot being played; out has room + 1 bytes. Returns the bytes stored.
extern "C" __declspec(dllexport) int __cdecl VF1Text_StoreName(const char *full, int room, char *out) {
    if (!full || !out || room <= 0 || room >= VF1_NAME_BOX_BYTES) return 0;
    return ShortFor(full, (int)Len(full), room, CurrentSlot(), out);
}
