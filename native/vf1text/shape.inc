// ---------------------------------------------------------------- right-to-left and shaped scripts (shape.inc)
// (included by vf1text.cpp before the drawing; patcher/vf1_shaping.py is the same rule; tests/test_shaping.py)
//
// Arabic, Hebrew, Syriac, Thaana, the Indic scripts, Thai, Lao, Tibetan, Myanmar, Khmer and the other scripts whose
// letters change shape with their neighbours or run right to left were drawn one whole character at a time, each in
// its isolated form and in logical order. Now a RUN of such letters -- with the spaces, digits and punctuation between
// them -- is drawn as ONE picture by GDI's TextOutW of the whole run, which shapes it (Uniscribe: joining forms,
// ligatures, conjuncts, stacked marks) and lays it out in visual order (the bidi algorithm with a left-to-right base),
// exactly as Windows draws it in any of its own windows. The run is kept in the glyph cache under its own key (a
// leading 0x02 and its UTF-8) and advances the text by its measured width, like any letter. Spaces before the first
// and after the last such letter stay the game's own. A run is at most MaxRunClusters whole characters (the pages are
// 1024 pixels wide); a longer one is cut there, at a space when there is one.
//
// The caret of a name box (the game draws it at x + GetWidth(text), 0x40D318, as the stock game does) is moved to
// the visual end of the text's last run when that run ends in a right-to-left letter: GetCharacterPlacementW
// (GCP_REORDER) tells where the last logical character landed.

struct CpRange { unsigned first, last; };
static const CpRange ComplexRanges[] = {         // sorted, not overlapping (patcher/vf1_shaping.py COMPLEX_RANGES)
    { 0x0590, 0x08FF },        // Hebrew, Arabic, Syriac, Arabic Supplement, Thaana, NKo, Samaritan, Mandaic, Arabic Extended
    { 0x0900, 0x0DFF },        // Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam, Sinhala
    { 0x0E00, 0x0EFF },        // Thai, Lao
    { 0x0F00, 0x0FFF },        // Tibetan
    { 0x1000, 0x109F },        // Myanmar
    { 0x1780, 0x17FF },        // Khmer
    { 0x1800, 0x18AF },        // Mongolian
    { 0x1900, 0x194F },        // Limbu
    { 0x1980, 0x19DF },        // New Tai Lue
    { 0x1A00, 0x1AAF },        // Buginese, Tai Tham
    { 0x1B00, 0x1BBF },        // Balinese, Sundanese, Batak
    { 0x1C00, 0x1C4F },        // Lepcha
    { 0xA800, 0xA82F },        // Syloti Nagri
    { 0xA880, 0xA8DF },        // Saurashtra
    { 0xA8E0, 0xA8FF },        // Devanagari Extended
    { 0xA900, 0xA95F },        // Kayah Li, Rejang
    { 0xA980, 0xA9DF },        // Javanese
    { 0xAA00, 0xAADF },        // Cham, Myanmar Extended-A, Tai Viet
    { 0xABC0, 0xABFF },        // Meetei Mayek
    { 0xFB1D, 0xFDFF },        // Hebrew and Arabic presentation forms A
    { 0xFE70, 0xFEFF },        // Arabic presentation forms B
    { 0x10800, 0x10FFF },      // the right-to-left historic scripts (Cypriot .. Old Uyghur)
    { 0x11000, 0x11FFF },      // Brahmi and the other Indic scripts of the supplementary plane
    { 0x1E800, 0x1EFFF },      // Mende Kikakui, Adlam, Arabic Mathematical
};

static bool IsComplex(unsigned cp) {
    int lo = 0, hi = (int)(sizeof ComplexRanges / sizeof ComplexRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < ComplexRanges[mid].first) hi = mid - 1;
        else if (cp > ComplexRanges[mid].last) lo = mid + 1;
        else return true;
    }
    return false;
}

// A character that belongs to the run around it: a space, a digit, ASCII and Latin-1 punctuation, general punctuation.
static bool IsRunNeutral(unsigned cp) {
    return cp == 0x20 || (cp >= 0x21 && cp <= 0x40) || (cp >= 0x5B && cp <= 0x60) || (cp >= 0x7B && cp <= 0x7E) ||
           (cp >= 0xA0 && cp <= 0xBF) || (cp >= 0x2000 && cp <= 0x206F);
}

static const int MaxRunClusters = 32;

// The end of the piece drawn as one that starts at whole character i: a run (above) or that one character.
static int PieceEnd(const unsigned *cps, int n, int i) {
    int j = ClusterEnd(cps, n, i);
    if (!IsComplex(cps[i])) return j;
    int clusters = 1, end = j, lastSpace = -1;
    for (int k = j; k < n && clusters < MaxRunClusters;) {
        int e = ClusterEnd(cps, n, k);
        if (IsComplex(cps[k])) { end = e; }
        else if (!IsRunNeutral(cps[k])) break;
        else if (cps[k] == 0x20) lastSpace = k;
        ++clusters;
        k = e;
    }
    if (clusters >= MaxRunClusters && lastSpace > 0 && lastSpace < end) end = lastSpace;   // a long run: cut at a space
    (void)lastSpace;
    return end;
}

// Whether the text has a run that holds a space (the word wrapper must not cut there: wrap.inc).
static bool HasGluedSpace(const unsigned *cps, int n) {
    for (int i = 0; i < n;) {
        int j = PieceEnd(cps, n, i);
        if (j - i > 1 && IsComplex(cps[i]))
            for (int k = i; k < j; ++k) if (cps[k] == 0x20) return true;
        i = j;
    }
    return false;
}

// ---- the caret of a name box
static const char *CaretText;                  // the text a name box is being drawn with (BoxDrawHook), or 0
static const unsigned CaretSite = 0x40D318;    // the box's Draw 0x40D140 drawing its caret at x + GetWidth(text)

typedef struct {
    unsigned lStructSize; wchar_t *lpOutString; unsigned *lpOrder; int *lpDx; int *lpCaretPos; char *lpClass;
    wchar_t *lpGlyphs; unsigned nGlyphs; int nMaxFit;
} GcpResults;

// How far from the text's right edge the caret goes: 0 when the text ends in anything but a run with a right-to-left
// last letter; else the run's width back, plus the visual x of the last logical character's trailing edge in the run.
static int CaretShift(void *impl, FontExtra *f, const char *text) {
    if (!f) return 0;
    int n = (int)Len(text);
    Run run;
    if (!DecodeRun(&run, text, n)) return 0;
    int shift = 0;
    int i = 0, last = -1;
    while (i < run.n) { last = i; i = PieceEnd(run.cps, run.n, i); }
    if (last >= 0 && IsComplex(run.cps[last]) && i - last > 0) {
        Letter l = LetterFor(f, impl, run.cps, last, i);
        GdiFace *g = ChooseFace(f->style, run.cps + last, i - last);
        if (l.extra && g && g->ok && GlyphDC) {
            wchar_t units[2 * 64 + 1];
            int u = 0, lastStart = 0;
            for (int k = last; k < i && u < 2 * 64; ++k) {
                lastStart = u;
                unsigned cp = run.cps[k];
                if (cp >= 0x10000) { units[u++] = (wchar_t)(0xD800 + ((cp - 0x10000) >> 10)); units[u++] = (wchar_t)(0xDC00 + ((cp - 0x10000) & 0x3FF)); }
                else units[u++] = (wchar_t)cp;
            }
            unsigned order[2 * 64]; int dx[4 * 64]; char cls[2 * 64 + 4];
            GcpResults r = { sizeof(GcpResults), 0, order, dx, 0, cls, 0, (unsigned)(2 * u), 0 };
            HGDIOBJ old = SelectObject(GlyphDC, g->font);
            DWORD ok = GetCharacterPlacementW(GlyphDC, units, u, 0, (GCP_RESULTSW *)&r, GCP_REORDER | GCP_LIGATE | GCP_GLYPHSHAPE);
            SelectObject(GlyphDC, old);
            if (ok && r.nGlyphs > 0 && cls[lastStart] == GCPCLASS_ARABIC) {      // GCPCLASS_HEBREW has the same value
                unsigned gi = order[lastStart];
                int xg = 0;
                for (unsigned k = 0; k < gi && k < r.nGlyphs; ++k) xg += dx[k];
                shift = -l.extra->w + l.extra->ox + xg;
            }
        }
    }
    FreeRun(&run);
    return shift;
}
