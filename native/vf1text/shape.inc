// ---------------------------------------------------------------- shaped and right-to-left scripts (shape.inc)
// (included by vf1text.cpp after the glyph code; patcher/vf1_shaping.py is the same rule; tests/test_shaping.py)
//
// Arabic, Hebrew, Syriac, Thaana, the Indic scripts, Thai, Lao, Tibetan, Myanmar, Khmer, Mongolian and the other
// scripts whose letters change shape with their neighbours or run right to left were drawn one whole character at a
// time, each in its isolated form and in logical order. Now a RUN of such letters is drawn as ONE piece: GDI's
// TextOutW of the whole run shapes it (Uniscribe: joining forms, ligatures, conjuncts, stacked marks) and lays it out
// in visual order (the bidi algorithm, left-to-right base), exactly as Windows draws it in its own windows, in the
// font's style like any letter Windows draws (glyph_gdi.inc). The Virtual Villagers patcher's rule (text_utf8.h
// ut_unit UT_RUN): a run is letters of one script with their marks, and the spaces between two of its words; any
// other character ends it. A run is at most MaxRunClusters whole characters (a page is 1024 pixels wide): a longer
// one is cut at its last space. A run no face of the chain has every letter of is drawn a character at a time, as
// before. Text with no such letter is drawn exactly as before.

struct ScriptRange { unsigned first, last; unsigned char group; bool rtl; };
static const ScriptRange ComplexRanges[] = {     // sorted, not overlapping (patcher/vf1_shaping.py COMPLEX_RANGES)
    { 0x0590, 0x05FF, 1, true },      // Hebrew
    { 0x0600, 0x08FF, 2, true },      // Arabic, Syriac, Arabic Supplement, Thaana, NKo, Samaritan, Mandaic, Arabic Ext.
    { 0x0900, 0x097F, 3, false },     // Devanagari
    { 0x0980, 0x09FF, 4, false },     // Bengali
    { 0x0A00, 0x0A7F, 5, false },     // Gurmukhi
    { 0x0A80, 0x0AFF, 6, false },     // Gujarati
    { 0x0B00, 0x0B7F, 7, false },     // Oriya
    { 0x0B80, 0x0BFF, 8, false },     // Tamil
    { 0x0C00, 0x0C7F, 9, false },     // Telugu
    { 0x0C80, 0x0CFF, 10, false },    // Kannada
    { 0x0D00, 0x0D7F, 11, false },    // Malayalam
    { 0x0D80, 0x0DFF, 12, false },    // Sinhala
    { 0x0E00, 0x0E7F, 13, false },    // Thai
    { 0x0E80, 0x0EFF, 14, false },    // Lao
    { 0x0F00, 0x0FFF, 15, false },    // Tibetan
    { 0x1000, 0x109F, 16, false },    // Myanmar
    { 0x1780, 0x17FF, 17, false },    // Khmer
    { 0x1800, 0x18AF, 18, false },    // Mongolian
    { 0x1900, 0x194F, 19, false },    // Limbu
    { 0x1980, 0x19DF, 20, false },    // New Tai Lue
    { 0x1A00, 0x1AAF, 21, false },    // Buginese, Tai Tham
    { 0x1B00, 0x1BBF, 22, false },    // Balinese, Sundanese
    { 0x1BC0, 0x1BFF, 23, false },    // Batak
    { 0x1C00, 0x1C4F, 24, false },    // Lepcha
    { 0xA800, 0xA82F, 25, false },    // Syloti Nagri
    { 0xA880, 0xA8DF, 26, false },    // Saurashtra
    { 0xA8E0, 0xA8FF, 3, false },     // Devanagari Extended
    { 0xA900, 0xA92F, 27, false },    // Kayah Li
    { 0xA930, 0xA95F, 28, false },    // Rejang
    { 0xA980, 0xA9DF, 29, false },    // Javanese
    { 0xA9E0, 0xA9FF, 16, false },    // Myanmar Extended-B
    { 0xAA00, 0xAA5F, 30, false },    // Cham
    { 0xAA60, 0xAA7F, 16, false },    // Myanmar Extended-A
    { 0xAA80, 0xAADF, 31, false },    // Tai Viet
    { 0xABC0, 0xABFF, 32, false },    // Meetei Mayek
    { 0xFB1D, 0xFB4F, 1, true },      // Hebrew presentation forms
    { 0xFB50, 0xFDFF, 2, true },      // Arabic presentation forms A
    { 0xFE70, 0xFEFF, 2, true },      // Arabic presentation forms B
    { 0x10800, 0x10FFF, 33, true },   // the right-to-left historic scripts (Cypriot .. Old Uyghur)
    { 0x11000, 0x11FFF, 34, false },  // Brahmi and the other Indic scripts of the supplementary plane
    { 0x1E800, 0x1EFFF, 35, true },   // Mende Kikakui, Adlam, Arabic Mathematical
};
static const int MaxRunClusters = 64;
static const int MaxRunBytes = 380;        // its UTF-8 must fit a letter's key (vf1text.cpp Extra::key)
static int Utf8Size(unsigned cp) { return cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4; }
static int Utf8Span(const unsigned *cps, int a, int b) { int n = 0; for (int k = a; k < b; ++k) n += Utf8Size(cps[k]); return n; }

static const ScriptRange *ComplexOf(unsigned cp) {
    int lo = 0, hi = (int)(sizeof ComplexRanges / sizeof ComplexRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < ComplexRanges[mid].first) hi = mid - 1;
        else if (cp > ComplexRanges[mid].last) lo = mid + 1;
        else return &ComplexRanges[mid];
    }
    return 0;
}
static int ScriptGroup(unsigned cp) { const ScriptRange *r = ComplexOf(cp); return r ? r->group : 0; }
static bool IsRtl(unsigned cp) { const ScriptRange *r = ComplexOf(cp); return r && r->rtl; }

// The end of the shaped run that starts at code point i (cps[i] is a letter of a shaped script), or 0 when the run
// is one whole character. The run takes the next whole characters of the same script, and spaces only when its
// script goes on after them.
static int RunEnd(const unsigned *cps, int n, int i) {
    int group = ScriptGroup(cps[i]);
    if (!group) return 0;
    int end = DrawEnd(cps, n, i), clusters = 1, lastSpace = -1, bytes = Utf8Span(cps, i, end);
    bool capped = false;
    for (int k = end; k < n;) {
        if (ScriptGroup(cps[k]) == group) {
            int e = DrawEnd(cps, n, k), add = Utf8Span(cps, k, e);
            if (clusters >= MaxRunClusters || bytes + add > MaxRunBytes || e - i > MaxLetterUnits) { capped = true; break; }
            end = k = e;
            bytes += add;
            ++clusters;
            continue;
        }
        if (cps[k] != ' ') break;
        int q = k;
        while (q < n && cps[q] == ' ') ++q;
        if (q >= n || ScriptGroup(cps[q]) != group) break;
        if (clusters + (q - k) >= MaxRunClusters || bytes + (q - k) > MaxRunBytes) { capped = true; break; }
        lastSpace = k;
        clusters += q - k;
        bytes += q - k;
        k = q;
    }
    if (capped && lastSpace > i) end = lastSpace;
    return end > DrawEnd(cps, n, i) ? end : 0;
}

// The piece the draw and measure loops take at code point i: a shaped run (when a face of the chain has every one of
// its letters), else DrawEnd's whole character.
static int PieceEnd(FontExtra *f, const unsigned *cps, int n, int i) {
    int j = DrawEnd(cps, n, i);
    int end = RunEnd(cps, n, i);
    if (!end || !f) return j;
    if (!f->style.ok || !ChooseFace(f->style, cps + i, end - i)) return j;
    return end;
}

// Whether the text has a right-to-left run with a space inside (the word wrapper keeps such a phrase together, so that
// its words are drawn in their visual order: wrap.inc).
static bool HasRtlPhrase(const unsigned *cps, int n) {
    for (int i = 0; i < n; ++i)
        if (cps[i] == ' ' && i > 0 && IsRtl(cps[i - 1])) {
            int q = i;
            while (q < n && cps[q] == ' ') ++q;
            if (q < n && ScriptGroup(cps[q]) == ScriptGroup(cps[i - 1])) return true;
        }
    return false;
}
