// ---------------------------------------------------------------- names in this DLL's own windows
// The patcher's one rule for text in the save (patcher/vf1_text.py, vf1text.dll): a name that is valid UTF-8 is
// UTF-8; any other name is one character per byte (Windows-1252, its five unassigned bytes as Latin-1). A name
// typed in this DLL's own windows (Spawn Child, Adopt Outside Child) is stored as UTF-8, cut only between whole
// characters (the same cluster table, generated from vf1_text.py). The stock game shows such a name as Latin-1
// letters; Render Unicode with In-Game Fonts or Use Unicode Font show it as typed.
#include "../vf1text/extenders.inc"

static const unsigned short NameCp1252[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152,
    0x008D, 0x017D, 0x008F, 0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122,
    0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178,
};

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

// One character limit for every name box (vf1text.dll / vf1font.dll, native/vf1text/names.inc): a name longer than
// its save field is kept there as its short form, the whole name in the save's Names file. Set by LoadTextCompanion
// when one of the two is installed; without them a name is only what fits its field.
typedef const char *(__cdecl *TextFullNameFn)(const char *stored);
typedef int (__cdecl *TextStoreNameFn)(const char *full, int room, char *out);
static TextFullNameFn TextFullName;
static TextStoreNameFn TextStoreName;

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
    int got = n ? MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes, n, out, VF1_NAME_BOX_BYTES + 7) : 0;
    if (got > 0 || n == 0) {
        out[got] = 0;
        return out;
    }
    int k = 0;
    for (int i = 0; i < n && k < VF1_NAME_BOX_BYTES + 7; ++i) {
        unsigned b = (unsigned char)bytes[i];
        out[k++] = (wchar_t)((b >= 0x80 && b < 0xA0) ? NameCp1252[b - 0x80] : b);
    }
    out[k] = 0;
    return out;
}

// `name` as UTF-8 in at most `room` bytes (plus a NUL) and VF1_NAME_LETTERS characters, cut only between whole
// characters (vf1_text.cut_to_bytes).
static int FitNameUtf8(const wchar_t *name, char *out, int room) {
    static unsigned cps[VF1_NAME_BOX_BYTES + 8];
    int n = 0, letters = 0;
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
    int used = 0;
    for (int i = 0; i < n;) {
        int j = i + 1;
        if (cps[i] >= 0x1F1E6 && cps[i] <= 0x1F1FF && j < n && cps[j] >= 0x1F1E6 && cps[j] <= 0x1F1FF) ++j;
        while (j < n) {
            if (cps[j] == 0x200D) { ++j; if (j < n) ++j; continue; }
            if (NameExtender(cps[j])) { ++j; continue; }
            break;
        }
        char piece[64];
        int bytes = 0;
        for (int k = i; k < j && bytes + 4 <= (int)sizeof piece; ++k) {
            unsigned c = cps[k];
            if (c < 0x80) piece[bytes++] = (char)c;
            else if (c < 0x800) { piece[bytes++] = (char)(0xC0 | (c >> 6)); piece[bytes++] = (char)(0x80 | (c & 0x3F)); }
            else if (c < 0x10000) {
                piece[bytes++] = (char)(0xE0 | (c >> 12)); piece[bytes++] = (char)(0x80 | ((c >> 6) & 0x3F));
                piece[bytes++] = (char)(0x80 | (c & 0x3F));
            } else {
                piece[bytes++] = (char)(0xF0 | (c >> 18)); piece[bytes++] = (char)(0x80 | ((c >> 12) & 0x3F));
                piece[bytes++] = (char)(0x80 | ((c >> 6) & 0x3F)); piece[bytes++] = (char)(0x80 | (c & 0x3F));
            }
        }
        if (used + bytes > room || letters == VF1_NAME_LETTERS) break;
        memcpy(out + used, piece, bytes);
        used += bytes;
        ++letters;
        i = j;
    }
    out[used] = 0;
    return used;
}

// A typed name into a member's 24-byte name field (plus its NUL): the name cut to the one limit; then its short form
// and the Names file when vf1text.dll / vf1font.dll is installed, else what fits the field.
static int StoreTypedName(const wchar_t *name, char *field25) {
    static char whole[VF1_NAME_BOX_BYTES + 1];
    if (FitNameUtf8(name, whole, VF1_NAME_BOX_BYTES) <= 0) return 0;
    if (TextStoreName) return TextStoreName(whole, 24, field25);
    return FitNameUtf8(name, field25, 24);
}

// For the tests (tests/test_vf1fun_names.py): the two rules, one call each.
extern "C" __declspec(dllexport) int __cdecl VF1Fun_FitName(const wchar_t *name, char *out, int room) {
    return FitNameUtf8(name, out, room);
}
extern "C" __declspec(dllexport) const wchar_t *__cdecl VF1Fun_NameW(const char *bytes, int cap) {
    return NameW(bytes, cap);
}
