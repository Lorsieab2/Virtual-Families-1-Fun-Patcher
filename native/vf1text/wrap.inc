// ---------------------------------------------------------------- line breaking for every script (wrap.inc)
// (included by vf1text.cpp after names.inc; patcher/vf1_line_break.py is the same rule in the patcher, and
// tests/test_line_break.py proves the two equal and the stock game unchanged)
//
// The game's justified word wrapper 0x409D70 (text, x, y, width, colour, font, measure only), ret 0x1C, cuts text into
// "words": a run of bytes that stops at a space or a line break, and right after a "." (not followed by another "."),
// a "," (not followed by a digit) or a "?". Lines are filled with whole words; between two words lies the width of a
// space, stretched to justify the line. A line that does not fit drops its last word to the next line, or squeezes
// each gap by a pixel when that is enough. Japanese, Chinese, Thai and other scripts written without spaces never
// wrapped, and a word wider than the whole line made the stock code loop for ever (it drops the line's only word and
// starts the same line again).
//
// Here (OwnWrap) the same algorithm runs with one change: a word may also be cut where the Unicode line-breaking rules
// (UAX #14) allow it next to a letter of a script written without spaces -- ideographs, kana, Hangul, Thai, Lao,
// Khmer, Myanmar, emoji -- and next to the CJK punctuation; the kinsoku rules come with UAX #14 (no line starts with
// 。、」 or a small kana, none ends with 「). The pieces of a word follow each other with no space between them,
// and only the spaces between words are stretched. A piece wider than the whole line is cut between whole characters
// (grapheme clusters), never inside one.
//
// The rules come from Windows' own ICU (icu.dll, Windows 10 1903 and later: ubrk_open(UBRK_LINE), which also knows the
// Thai, Lao, Khmer and Myanmar words); without it, a small built-in table (linebreak.inc, the CJK basics).
//
// A text with no such letter, whose every word fits the line, is wrapped by the game's own code, untouched: stock
// text is laid out exactly as before, pixel for pixel.

#include "linebreak.inc"
#include "wordlists.inc"

typedef int (__thiscall *GetHeightFn)(void *font, void *scale);
static const GetHeightFn GetHeight = (GetHeightFn)0x4023F0;
static const unsigned SpaceText = 0x4B27BC;               // " "
static const unsigned JustifyRatio = 0x4B27B8;            // the float the stock wrapper compares a line's fill with

// ---- ICU, loaded once from System32
typedef void *(__cdecl *UbrkOpenFn)(int type, const char *locale, const wchar_t *text, int length, int *status);
typedef int (__cdecl *UbrkStepFn)(void *it);
typedef void (__cdecl *UbrkCloseFn)(void *it);
typedef int (__cdecl *UPropertyFn)(unsigned cp, int which);
static UbrkOpenFn UbrkOpen;
static UbrkStepFn UbrkFirst, UbrkNext;
static UbrkCloseFn UbrkClose;
static UPropertyFn UProperty;
static bool IcuLooked;

static bool LoadIcu() {
    if (!IcuLooked) {
        IcuLooked = true;
        HMODULE m = LoadLibraryExW(L"icu.dll", 0, 0x800 /* LOAD_LIBRARY_SEARCH_SYSTEM32 */);
        if (m) {
            UbrkOpen = (UbrkOpenFn)GetProcAddress(m, "ubrk_open");
            UbrkFirst = (UbrkStepFn)GetProcAddress(m, "ubrk_first");
            UbrkNext = (UbrkStepFn)GetProcAddress(m, "ubrk_next");
            UbrkClose = (UbrkCloseFn)GetProcAddress(m, "ubrk_close");
            UProperty = (UPropertyFn)GetProcAddress(m, "u_getIntPropertyValue");
            if (!UbrkOpen || !UbrkFirst || !UbrkNext || !UbrkClose || !UProperty) UbrkOpen = 0;
        }
    }
    return UbrkOpen != 0;
}

// A letter of a script written without spaces: the CJK punctuation blocks, and ICU's line-break classes ID, SA, H2,
// H3, JL, JT, JV, CJ, EB and EM (the built-in table's ideographic class without ICU).
static bool NoSpaceLetter(unsigned cp) {
    if ((cp >= 0x3000 && cp <= 0x303F) || (cp >= 0xFE30 && cp <= 0xFE4F) || (cp >= 0xFF00 && cp <= 0xFFEF)) return true;
    if (LoadIcu()) {
        int c = UProperty(cp, 0x1008 /* UCHAR_LINE_BREAK */);
        return c == 14 || c == 24 || (c >= 31 && c <= 35) || c == 37 || c == 40 || c == 41;
    }
    return FallbackClass(cp) == LbIdeographic;
}

// Where a word may be cut, by byte offset (out[b] for 0 < b < n): only between whole characters, next to a letter of
// a script written without spaces (or after a zero width space), never after a space, and only where UAX #14 allows.
// Returns whether the text has any such letter.
static bool BreaksFor(const unsigned char *text, int n, unsigned char *out) {
    for (int b = 0; b <= n; ++b) out[b] = 0;
    Run run;
    if (!DecodeRun(&run, (const char *)text, n)) return false;
    bool any = false;
    for (int i = 0; i < run.n; ++i) if (NoSpaceLetter(run.cps[i]) || run.cps[i] == 0x200B) { any = true; break; }
    if (!any) { FreeRun(&run); return false; }
    // each code point's byte offset, the text in UTF-16, and ICU's boundaries by code point
    int *at = (int *)Alloc(sizeof(int) * (unsigned)(run.n + 1));
    unsigned char *icu = (unsigned char *)Alloc((unsigned)run.n + 1);
    wchar_t *units = (wchar_t *)Alloc(sizeof(wchar_t) * (unsigned)(2 * run.n + 1));
    int *unitCp = (int *)Alloc(sizeof(int) * (unsigned)(2 * run.n + 1));
    if (!at || !icu || !units || !unitCp) { Free(at); Free(icu); Free(units); Free(unitCp); FreeRun(&run); return true; }
    int u = 0;
    at[0] = 0;
    for (int i = 0; i < run.n; ++i) {
        at[i + 1] = at[i] + run.widths[i];
        unsigned cp = run.cps[i];
        unitCp[u] = i;
        if (cp >= 0x10000) {
            units[u++] = (wchar_t)(0xD800 + ((cp - 0x10000) >> 10));
            unitCp[u] = i;
            units[u++] = (wchar_t)(0xDC00 + ((cp - 0x10000) & 0x3FF));
        } else {
            units[u++] = (wchar_t)cp;
        }
    }
    unitCp[u] = run.n;
    bool useIcu = false;
    if (LoadIcu()) {
        int status = 0;
        void *it = UbrkOpen(2 /* UBRK_LINE */, "", units, u, &status);
        if (it && status <= 0) {
            useIcu = true;
            for (int b = UbrkFirst(it); b >= 0 && b <= u; b = UbrkNext(it))
                if (b == 0 || b == u || unitCp[b - 1] != unitCp[b]) icu[unitCp[b]] = 1;   // never inside a pair
        }
        if (it) UbrkClose(it);
    }
    // without ICU: the words of the shared word lists (wordlists.inc) are never cut
    unsigned char *inside = 0;
    if (!useIcu) {
        int *ends = (int *)Alloc(sizeof(int) * (unsigned)(run.n + 1));
        inside = (unsigned char *)Alloc((unsigned)run.n + 1);
        if (ends && inside) {
            for (int i = 0; i < run.n; ++i) ends[i] = DrawEnd(run.cps, run.n, i);
            ends[run.n] = run.n;
            DictionaryInside(run.cps, run.n, ends, inside);
        }
        Free(ends);
    }
    int prev = -1;                                      // where the cluster before starts
    for (int i = 0; i < run.n;) {
        int j = DrawEnd(run.cps, run.n, i);
        if (prev >= 0) {
            unsigned before = run.cps[prev], after = run.cps[i], last = run.cps[i - 1];
            bool ok = before != ' ' && before != '\n' && after != ' ' && after != '\n' &&
                      (NoSpaceLetter(before) || NoSpaceLetter(after) || last == 0x200B);
            if (ok) ok = useIcu ? icu[i] != 0 : (last == 0x200B || FallbackMayBreak(before, after));   // LB8: after U+200B
            if (ok && inside && inside[i]) ok = false;
            if (ok) out[at[i]] = 1;
        }
        prev = i;
        i = j;
    }
    Free(at); Free(icu); Free(units); Free(unitCp); Free(inside);
    FreeRun(&run);
    return true;
}

// The end of the stock wrapper's word that starts at byte `at` (0x409E95..0x409EE3): its spaces, then up to a space,
// a line break or the end, or just after a "." not followed by ".", a "," not followed by a digit, or a "?".
static int WordEnd(const unsigned char *s, int at) {
    while (s[at] == ' ') ++at;
    for (bool stop = false; s[at] && !stop;) {
        unsigned char c = s[at];
        if (c == ' ' || c == '\n') break;
        ++at;
        if (c == '.') stop = s[at] != '.';
        else if (c == ',') stop = !(s[at] >= '0' && s[at] <= '9');
        else if (c == '?') stop = true;
    }
    return at;
}

// OwnWrap's word (shape.inc): the stock word, and, when it ends in a letter of a right-to-left script and that script
// goes on after its spaces, the next word too -- a right-to-left phrase is kept together, so that its words are drawn
// as one shaped run in their visual order (a phrase wider than the line is cut at a space: EmergencyCut).
static unsigned CpBefore(const unsigned char *s, int start, int end) {
    int p = end - 1;
    while (p > start && (s[p] & 0xC0) == 0x80 && end - p < 4) --p;
    unsigned cp = 0;
    return Utf8At(s + p, end - p, &cp) == end - p ? cp : 0;
}
static int OwnWordEnd(const unsigned char *s, int at) {
    int end = WordEnd(s, at);
    while (s[end] == ' ') {
        unsigned before = CpBefore(s, at, end), after = 0;
        int q = end;
        while (s[q] == ' ') ++q;
        int n = 0;
        while (s[q + n] && n < 4) ++n;
        if (!s[q] || !IsRtl(before) || !Utf8At(s + q, n, &after) || ScriptGroup(after) != ScriptGroup(before)) break;
        end = WordEnd(s, end);
    }
    return end;
}
static int PieceWidth(void *impl, const char *text, int start, int len, unsigned colour, void *font) {
    return DrawStringN(impl, 0, text + start, len, 0, 0, true, colour, font);
}

// Would the stock code lay this text out? Every word must fit the line when it starts one: alone (the stock code
// drops the spaces before a word that starts a wrapped line) and with its spaces at the text's start or after a line
// break (kept there). The stock code loops for ever on a word that does not.
static bool StockWordsFit(void *impl, const char *text, int width, unsigned colour, void *font) {
    const unsigned char *s = (const unsigned char *)text;
    bool lineStart = true;
    for (int at = 0; s[at];) {
        if (s[at] == '\n') { lineStart = true; ++at; continue; }
        int spaces = at;
        while (s[at] == ' ') ++at;
        if (!s[at]) break;
        if (s[at] == '\n') continue;
        int end = WordEnd(s, at);
        if (PieceWidth(impl, text, at, end - at, colour, font) > width) return false;
        if (lineStart && spaces < at && PieceWidth(impl, text, spaces, end - spaces, colour, font) > width) return false;
        lineStart = false;
        at = end;
    }
    return true;
}

struct WrapPiece { int start, len, width; bool glued; };

// The longest start of text[start, start+len) in whole characters no wider than `room` (at least one character).
static int EmergencyCut(void *impl, const char *text, int start, int len, int room, unsigned colour, void *font) {
    Run run;
    if (!DecodeRun(&run, text + start, len)) return len;
    int used = 0, best = 0;
    for (int i = 0; i < run.n;) {
        int j = DrawEnd(run.cps, run.n, i);
        for (int k = i; k < j; ++k) used += run.widths[k];
        if (best && PieceWidth(impl, text, start, used, colour, font) > room) break;
        best = used;
        i = j;
    }
    FreeRun(&run);
    // a right-to-left phrase (OwnWordEnd) is cut at its last space that fits, not inside a word
    if (best && best < len) {
        const unsigned char *s = (const unsigned char *)text + start;
        for (int k = best; k > 0; --k)
            if (s[k] == ' ' && s[k - 1] != ' ') { best = k; break; }
    }
    return best ? best : len;
}

// 0x409D70 with breaks inside words (see the top of this file): the same steps, in the same order, as the stock code;
// a word is one or more pieces (cut at `breaks`), and only a word's first piece has a space before it.
static int OwnWrap(void *outer, const char *text, int x, int y, int width, unsigned colour, void *font, bool measureOnly,
                   const unsigned char *breaks) {
    void *impl = *(void **)outer;
    if (!font) font = *(void **)((char *)impl + 0x5C);
    if (!font) return 0;
    int spaceW = DrawStringN(impl, 0, (const char *)SpaceText, 1, 0, 0, true, colour, font);
    int maxGap = (spaceW * 5) / 3;
    int height = GetHeight(font, 0);
    const unsigned char *s = (const unsigned char *)text;
    WrapPiece piece[100];
    int at = 0, yoff = 0;
    bool afterBreak = true;                                  // [esp+0x12]: the line follows a line break
    for (;;) {
        // 0x409E05: line breaks
        if (s[at] == '\n') {
            while (s[at] == '\n') { yoff += height; ++at; afterBreak = true; }
            if (!s[at]) return yoff;
        }
        if (!afterBreak) while (s[at] == ' ') ++at;          // 0x409E38: a wrapped line drops its spaces
        if (!s[at]) return yoff;
        // 0x409E6A: fill a line
        int lineW = 0, count = 0, gaps = 0, extra = 0;
        for (;;) {
            if (!afterBreak && s[at] == ' ') ++at;           // the one space between two words
            afterBreak = false;
            int wordStart = at, end = OwnWordEnd(s, at);
            bool full = false;
            // (a word may be empty: spaces at the end of the text make one, which the stock code counts too)
            for (int p = wordStart;;) {
                int q = p;
                if (p < end) {
                    q = p + 1;
                    while (q < end && !breaks[q]) ++q;
                }
                bool glued = p != wordStart;
                int w = PieceWidth(impl, text, p, q - p, colour, font);
                if (!glued && count > 0) { lineW += spaceW; ++gaps; }
                lineW += w;
                piece[count].start = p; piece[count].len = q - p; piece[count].width = w; piece[count].glued = glued;
                ++count;
                if (lineW > width) {                         // 0x409F86
                    full = true;
                    if (lineW - width < gaps) {              // squeeze every gap by a pixel
                        extra = -1;
                        at = q;
                        if (s[at] == '\n') ++at;
                    } else if (count == 1) {                 // wider than the whole line: cut between characters
                        int keep = EmergencyCut(impl, text, p, q - p, width, colour, font);
                        piece[0].len = keep;
                        piece[0].width = PieceWidth(impl, text, p, keep, colour, font);
                        lineW = piece[0].width;
                        at = p + keep;
                    } else {                                 // to the next line (its space's width stays counted)
                        --count;
                        lineW -= w;
                        if (!glued) --gaps;
                        at = p;
                    }
                    break;
                }
                p = q;
                if (p >= end) break;
                if (lineW == width || count == 100) { full = true; at = p; break; }
            }
            if (full) break;
            at = end;
            // 0x409F2E
            if (!s[at] || lineW == width || count == 100) break;
            if (s[at] == '\n') { afterBreak = true; ++at; break; }
        }
        // 0x409F55
        if (!measureOnly) {
            int free = gaps * spaceW - lineW + width;
            int gap = gaps ? free / gaps : 0;
            int rem = free - gap * gaps;
            bool justify = gaps != 0;
            bool lastOfText = !s[at] && at > 0 && (s[at - 1] == '.' || s[at - 1] == '?');
            if (justify) {
                if (gap > maxGap && (float)((double)lineW / (double)width) < *(float *)JustifyRatio) justify = false;
                else if (lastOfText) justify = false;
            }
            if (!justify) { gap = extra + spaceW; rem = 0; }
            // 0x40A020: word by word (a word's pieces are drawn as one)
            int left = gaps, xx = x;
            for (int k = 0, g = 0; k < count; ++g) {
                int e = k + 1, w = piece[k].width;
                while (e < count && piece[e].glued) { w += piece[e].width; ++e; }
                if (justify && g == gaps) xx = x - w + width;
                int len = piece[e - 1].start + piece[e - 1].len - piece[k].start;
                DrawStringN(impl, 0, text + piece[k].start, len, xx, y + yoff, false, colour, font);
                xx += w + gap;
                if (left-- <= rem) xx += 1;
                k = e;
            }
        }
        yoff += height;                                      // 0x40A0B9
    }
}

static bool TextHasRtlPhrase(const char *text, int n) {
    Run run;
    if (!DecodeRun(&run, text, n)) return false;
    bool r = HasRtlPhrase(run.cps, run.n);
    FreeRun(&run);
    return r;
}

// 0x409D70 after whole names (names.inc): the game's own code when it lays the text out as before, else OwnWrap.
static int WrapText(void *window, const char *shown, int x, int y, int width, unsigned colour, void *font, int measure) {
    void *impl = *(void **)window;
    void *f = font ? font : (impl ? *(void **)((char *)impl + 0x5C) : 0);
    int n = (int)Len(shown);
    unsigned char *breaks = f ? (unsigned char *)Alloc((unsigned)n + 1) : 0;
    bool own = false;
    if (breaks) {
        bool any = BreaksFor((const unsigned char *)shown, n, breaks);
        own = any || !StockWordsFit(impl, shown, width, colour, f) || TextHasRtlPhrase(shown, n);
    }
    int r = own ? OwnWrap(window, shown, x, y, width, colour, font, (measure & 0xFF) != 0, breaks)
                : ((WrapFn)(void *)&WrapStock)(window, shown, x, y, width, (int)colour, font, measure);
    Free(breaks);
    return r;
}
