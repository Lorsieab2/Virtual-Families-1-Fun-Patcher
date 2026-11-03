// ---------------------------------------------------------------- names in this DLL's own windows
// The patcher's one rule for text in the save (patcher/vf1_text.py, vf1text.dll, native/vf1text/text_rule.inc): a
// Windows-1252 character is stored as its one byte, any other character as UTF-8, in the same string (all UTF-8 when
// the mix would read back differently); it is read per sequence: each well-formed UTF-8 sequence is its character,
// every other byte is Windows-1252 (its five unassigned bytes as Latin-1). A name typed in this DLL's own windows
// (Spawn Child, Adopt Outside Child) is stored by that rule, cut only between whole characters (the same cluster table,
// generated from vf1_text.py). The stock game shows such a name as Latin-1 letters where it must (the characters
// outside Windows-1252); Render Unicode with In-Game Fonts or Use Unicode Font show it as typed.
#include "../vf1text/extenders.inc"
#include "../vf1text/text_rule.inc"

static bool NameExtender(unsigned cp) {
    int lo = 0, hi = (int)(sizeof ExtenderRanges / sizeof ExtenderRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < ExtenderRanges[mid][0]) hi = mid - 1;
        else if (cp > ExtenderRanges[mid][1]) lo = mid + 1;
        else return true;
    }
    return false;
}

// One limit for every name box (vf1text.dll / vf1font.dll, native/vf1text/names.inc): a name longer than
// its save field is kept there as its short form, the whole name in the save's Names file. Set by LoadTextCompanion
// when one of the two is installed; without them a name is only what fits its field.
typedef const char *(__cdecl *TextFullNameFn)(const char *stored);
typedef int (__cdecl *TextStoreNameFn)(const char *full, int room, char *out);
static TextFullNameFn TextFullName;
typedef int (__stdcall *TextActiveFn)();
static TextActiveFn TextActive;      // VF1Text_UnicodeTextActive: nonzero only once the text DLL's hooks are installed
static TextStoreNameFn TextStoreName;
typedef void (__cdecl *TextFlushNamesFn)();
static TextFlushNamesFn TextFlushNames;   // VF1Text_FlushNames: writes every Names record not in its file yet

// `bytes` (n bytes of stored text) as UTF-16 by the per-sequence rule into out (at most cap units; a NUL follows).
// Returns the units written.
static int DecodeStoredW(const char *bytes, int n, wchar_t *out, int cap) {
    int k = 0;
    for (int i = 0; i < n;) {
        unsigned cp;
        int w = Utf8At((const unsigned char *)bytes + i, n - i, &cp);
        if (!w) { cp = SingleCp((unsigned char)bytes[i]); w = 1; }
        if (cp >= 0x10000) {
            if (k + 2 > cap) break;
            out[k++] = (wchar_t)(0xD800 + ((cp - 0x10000) >> 10));
            out[k++] = (wchar_t)(0xDC00 + ((cp - 0x10000) & 0x3FF));
        } else {
            if (k + 1 > cap) break;
            out[k++] = (wchar_t)cp;
        }
        i += w;
    }
    out[k] = 0;
    return k;
}

// The name in a save field (up to its NUL or `cap` bytes) as text for a window, by the one rule: the whole name when
// it is a short form. The result lives until four more names have been read.
static const wchar_t *NameW(const char *bytes, int cap = 64) {
    static wchar_t ring[4][VF1_NAME_BOX_BYTES + 8];
    static int next;
    wchar_t *out = ring[next];
    next = (next + 1) & 3;
    out[0] = 0;
    if (!bytes) return out;
    char field[64];
    if (TextFullName && cap < (int)sizeof field) {
        int k = 0;
        while (k < cap && bytes[k]) { field[k] = bytes[k]; ++k; }
        field[k] = 0;
        const char *whole = TextFullName(field);
        if (whole && whole != field) { bytes = whole; cap = VF1_NAME_BOX_BYTES; }
    }
    int n = 0;
    while (n < cap && bytes[n]) ++n;
    DecodeStoredW(bytes, n, out, VF1_NAME_BOX_BYTES + 6);
    return out;
}

// `name` stored by the write rule in at most `room` bytes (plus a NUL), cut only between whole characters
// (vf1_text.cut_to_bytes: a start's stored length never shrinks as it grows, so the cut is found by halving).
static int FitNameStored(const wchar_t *name, char *out, int room) {
    static unsigned cps[VF1_NAME_BOX_BYTES + 8];
    static int ends[VF1_NAME_BOX_BYTES + 8];
    static unsigned char tmp[4 * (VF1_NAME_BOX_BYTES + 8)];
    int n = 0;
    for (int i = 0; name && name[i] && n < VF1_NAME_BOX_BYTES + 8; ++i) {
        unsigned c = name[i];
        if (c >= 0xD800 && c <= 0xDBFF && name[i + 1] >= 0xDC00 && name[i + 1] <= 0xDFFF) {
            c = 0x10000 + ((c - 0xD800) << 10) + (name[i + 1] - 0xDC00);
            ++i;
        } else if (c >= 0xD800 && c <= 0xDFFF) {
            continue;                                   // an unpaired surrogate is never stored
        }
        if (c < 0x20 || (c >= 0x7F && c < 0xA0)) continue;   // nor a control character
        cps[n++] = c;
    }
    int count = 0;
    for (int i = 0; i < n;) {
        int j = i + 1;
        // vf1_text.clusters (control characters, CR and LF among them, were dropped above, so CR LF never occurs)
        if (cps[i] >= 0x1F1E6 && cps[i] <= 0x1F1FF && j < n && cps[j] >= 0x1F1E6 && cps[j] <= 0x1F1FF) ++j;
        while (j < n) {
            if (cps[j] == 0x200D) { ++j; if (j < n && cps[j] != '\r' && cps[j] != '\n') ++j; continue; }
            if (NameExtender(cps[j])) { ++j; continue; }
            break;
        }
        ends[count++] = j;
        i = j;
    }
    int lo = 0, hi = count;
    while (lo < hi) {
        int mid = (lo + hi + 1) / 2;
        if (EncodeStored(cps, ends[mid - 1], tmp) <= room) lo = mid; else hi = mid - 1;
    }
    int used = lo ? EncodeStored(cps, ends[lo - 1], tmp) : 0;
    memcpy(out, tmp, used);
    out[used] = 0;
    return used;
}

// A typed name into a member's 24-byte name field (plus its NUL): the name cut to the one limit; then its short form
// and the Names file when vf1text.dll / vf1font.dll is installed, else what fits the field.
static int StoreTypedName(const wchar_t *name, char *field25) {
    static char whole[VF1_NAME_BOX_BYTES + 1];
    if (FitNameStored(name, whole, VF1_NAME_BOX_BYTES) <= 0) return 0;
    if (TextStoreName) return TextStoreName(whole, 24, field25);
    return FitNameStored(name, field25, 24);
}

// For the tests (tests/test_vf1fun_names.py): the two rules, one call each.
extern "C" __declspec(dllexport) int __cdecl VF1Fun_FitName(const wchar_t *name, char *out, int room) {
    return FitNameStored(name, out, room);
}
extern "C" __declspec(dllexport) const wchar_t *__cdecl VF1Fun_NameW(const char *bytes, int cap) {
    return NameW(bytes, cap);
}
