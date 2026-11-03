// ---------------------------------------------------------------- word lists for line breaking (wordlists.inc)
// (included by wrap.inc; patcher/vf1_line_break.py `dictionary_inside` is the same rule in the patcher, and
// tests/test_word_lists.py proves the two equal)
//
// Thai, Lao, Khmer, Burmese, Chinese and Japanese are written without spaces between words, so a line can only be
// broken well with a word list. Windows' own icu.dll knows the words (wrap.inc asks it first). Without icu.dll (Windows
// before 10 version 1903) the shared ICU 77-1 word lists, shipped unchanged in "Unicode Text\Word Lists\" (vf1font.dll: "Unicode Font\Word Lists\") beside this DLL (the four
// Fun Patchers' copy, unicode-audit/word-lists), are used: each run of letters of one of these scripts is cut into
// words by longest match, and a line may then break only between two words (the usual rules still apply there:
// linebreak.inc's kinsoku table). A list is read only the first time text of its script needs it, and only when
// icu.dll is missing; a list that is missing or cannot be read leaves the built-in table's breaks as they were.

enum { WlThai, WlLao, WlKhmer, WlBurmese, WlCj, WlCount };

struct WordList {
    const wchar_t *file;
    bool looked;
    unsigned char *data;              // the file, each word NUL-ended in place (VirtualAlloc)
    unsigned *slots;                  // open addressing: offset + 1 of a word in data, 0 empty (VirtualAlloc)
    unsigned mask;
    int longest;                      // the longest word, in code points
};
static WordList WordLists[WlCount] = {
    { L"thaidict.txt" }, { L"laodict.txt" }, { L"khmerdict.txt" }, { L"burmesedict.txt" }, { L"cjdict.txt" },
};
static const wchar_t WordListFolder[] = L"Word Lists\\";

// Which list a letter's words are in, or -1.
static int WordListFor(unsigned cp) {
    if (cp >= 0x0E00 && cp <= 0x0E7F) return WlThai;
    if (cp >= 0x0E80 && cp <= 0x0EFF) return WlLao;
    if ((cp >= 0x1780 && cp <= 0x17FF) || (cp >= 0x19E0 && cp <= 0x19FF)) return WlKhmer;
    if ((cp >= 0x1000 && cp <= 0x109F) || (cp >= 0xA9E0 && cp <= 0xA9FF) || (cp >= 0xAA60 && cp <= 0xAA7F)) return WlBurmese;
    if ((cp >= 0x3041 && cp <= 0x30FF && cp != 0x30FB) || (cp >= 0x31F0 && cp <= 0x31FF) || (cp >= 0x3400 && cp <= 0x4DBF) ||
        (cp >= 0x4E00 && cp <= 0x9FFF) || (cp >= 0xF900 && cp <= 0xFAFF) || (cp >= 0xFF66 && cp <= 0xFF9F) ||
        (cp >= 0x20000 && cp <= 0x3FFFF) || cp == 0x3005)
        return WlCj;
    return -1;
}

static unsigned WordHash(const unsigned char *s, unsigned n) {
    unsigned h = 2166136261u;                                   // FNV-1a
    for (unsigned i = 0; i < n; ++i) { h ^= s[i]; h *= 16777619u; }
    return h;
}

static void *BigAlloc(unsigned n) { return VirtualAlloc(0, n, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE); }
static void BigFree(void *p) { if (p) VirtualFree(p, 0, MEM_RELEASE); }

// Reads list k once: UTF-8 (with or without a byte order mark), "#" lines are comments, one word a line, anything
// after a tab (cjdict.txt's frequency) or a space is not part of the word.
static bool LoadWordList(int k) {
    WordList *w = &WordLists[k];
    if (w->looked) return w->slots != 0;
    w->looked = true;
    unsigned fl = WLen(Folder), dl = WLen(WordListFolder), nl = WLen(w->file);
    if (!fl || fl + dl + nl + 1 > MAX_PATH) return false;
    wchar_t path[MAX_PATH];
    Copy(path, Folder, fl * 2);
    Copy(path + fl, WordListFolder, dl * 2);
    Copy(path + fl + dl, w->file, (nl + 1) * 2);
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, 0, 0);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD hi = 0, size = GetFileSize(h, &hi);
    unsigned char *data = 0;
    if (hi == 0 && size > 0 && size < 64u * 1024 * 1024) {
        data = (unsigned char *)BigAlloc(size + 1);
        DWORD got = 0;
        if (data && (!ReadFile(h, data, size, &got, 0) || got != size)) { BigFree(data); data = 0; }
    }
    CloseHandle(h);
    if (!data) return false;
    data[size] = 0;
    // cut the lines into words, in place; count them
    unsigned count = 0, at = (size >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF) ? 3 : 0;
    for (unsigned p = at; p < size;) {
        unsigned e = p;
        while (e < size && data[e] != '\n') ++e;
        unsigned w_end = p;
        while (w_end < e && data[w_end] != '\t' && data[w_end] != ' ' && data[w_end] != '\r') ++w_end;
        bool word = w_end > p && data[p] != '#';
        for (unsigned q = word ? w_end : p; q < e; ++q) data[q] = 0;
        if (e < size) data[e] = 0;
        if (word) ++count;
        p = e + 1;
    }
    unsigned slots = 1024;
    while (slots < count * 2) slots *= 2;
    w->slots = (unsigned *)BigAlloc(slots * 4);
    if (!w->slots) { BigFree(data); return false; }
    w->mask = slots - 1;
    w->data = data;
    for (unsigned p = at; p < size;) {
        unsigned n = 0;
        while (data[p + n]) ++n;
        if (n) {
            int letters = 0;
            for (unsigned q = 0; q < n; ++q) if ((data[p + q] & 0xC0) != 0x80) ++letters;
            if (letters > w->longest) w->longest = letters;
            unsigned s = WordHash(data + p, n) & w->mask;
            while (w->slots[s]) {
                const unsigned char *o = data + w->slots[s] - 1;
                unsigned m = 0;
                while (o[m] && m < n && o[m] == data[p + m]) ++m;
                if (m == n && !o[m]) break;                    // already there
                s = (s + 1) & w->mask;
            }
            if (!w->slots[s]) w->slots[s] = p + 1;
        }
        p += n + 1;
        while (p < size && !data[p]) ++p;
    }
    return true;
}

static bool InWordList(const WordList *w, const unsigned char *s, unsigned n) {
    unsigned i = WordHash(s, n) & w->mask;
    while (w->slots[i]) {
        const unsigned char *o = w->data + w->slots[i] - 1;
        unsigned m = 0;
        while (m < n && o[m] == s[m]) ++m;
        if (m == n && !o[m]) return true;
        i = (i + 1) & w->mask;
    }
    return false;
}

// inside[i] = 1 where a line must not break before code point i because it lies inside a word of a list (i at a
// piece start of `ends`: ends[i] is where the piece starting at i ends, DrawEnd's pieces). Only runs of letters of one
// list's script are looked at; inside a run the longest word of the list that starts at each place is taken (up to the
// list's longest word, ending at a piece end), else one piece.
static void DictionaryInside(const unsigned *cps, int n, const int *ends, unsigned char *inside) {
    for (int i = 0; i <= n; ++i) inside[i] = 0;
    unsigned char *utf8 = 0;
    int *at = 0;
    for (int i = 0; i < n;) {
        int k = WordListFor(cps[i]);
        if (k < 0) { i = ends[i]; continue; }
        int runEnd = i;
        while (runEnd < n && WordListFor(cps[runEnd]) == k) runEnd = ends[runEnd];
        if (!LoadWordList(k)) { i = runEnd; continue; }
        if (!utf8) {
            utf8 = (unsigned char *)Alloc((unsigned)n * 4 + 4);
            at = (int *)Alloc(sizeof(int) * (unsigned)(n + 1));
            if (!utf8 || !at) break;
            at[0] = 0;
            for (int q = 0; q < n; ++q) at[q + 1] = at[q] + Utf8Put(cps[q], utf8 + at[q]);
        }
        const WordList *w = &WordLists[k];
        for (int p = i; p < runEnd;) {
            int best = 0;
            for (int e = ends[p]; e <= runEnd; e = ends[e]) {
                if (e - p > w->longest) break;
                if (InWordList(w, utf8 + at[p], (unsigned)(at[e] - at[p]))) best = e;
                if (e == runEnd) break;
            }
            if (!best) best = ends[p];
            for (int q = p + 1; q < best; ++q) inside[q] = 1;
            p = best;
        }
        i = runEnd;
    }
    Free(utf8);
    Free(at);
}
