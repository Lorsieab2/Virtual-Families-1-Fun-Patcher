// ---------------------------------------------------------------- nothing runs off the screen (screen.inc)
// (included by vf1text.cpp after wrap.inc; native/vf1tr/screen_tr.inc is the same rule for the game's own drawing
// when neither Unicode DLL is in; patcher/vf1_screen_edge.py is the model; tests/test_screen_edge.py)
//
// The owner, 2026-11-03: "i dont care if things run out of boxes, they just need to not run off the screen". A text
// the game draws (DrawString 0x409660: every left, right-aligned and centred draw and every text box ends there) or
// wraps (0x409D70) that would leave the screen, but is partly on it, is moved so that it ends at the screen's edge;
// one wider than the screen is cut, each line, to its longest start of whole characters and "…"; one taller than the
// screen keeps the lines that fit, the last ending in "…". (A wrapped text is already broken at the wrapper's own line
// breaks.) Only text the patches or a translation bring is touched -- text with a letter beyond ASCII, or any text
// while a translation is chosen -- so the stock English game is drawn exactly as before, and a text wholly off the
// screen (an animation not yet in view) is left as it is.

typedef int (__cdecl *TrActiveFn)();
typedef const char *(__cdecl *TrEnglishOfFn)(const char *);

static bool TranslationChosen() {
    static TrActiveFn active;                                     // vf1tr.dll loads after this DLL: looked for until found
    if (!active) {
        HMODULE tr = GetModuleHandleW(L"vf1tr.dll");
        active = tr ? (TrActiveFn)GetProcAddress(tr, "VF1Tr_Active") : 0;
    }
    return active && active() != 0;
}

static bool ClampWanted(const char *text, int n) {
    for (int i = 0; i < n; ++i) if ((unsigned char)text[i] >= 0x80) return true;
    return TranslationChosen();
}

static bool ScreenSize(void *window, int *w, int *h) {
    SDL_Surface *s = window ? *(SDL_Surface **)((char *)window + 0x30) : 0;
    if (!s || s->w <= 0 || s->h <= 0) return false;
    *w = s->w;
    *h = s->h;
    return true;
}

// `text` with every line no wider than `room` (FitToRoom) and at most `maxLines` lines, the last kept one ending in
// "…" when lines were dropped; on the heap (*owned).
static const char *CutLines(const char *text, void *impl, int room, int maxLines, char **owned) {
    int n = (int)Len(text);
    char *out = (char *)Alloc((unsigned)n + 8);
    char *line = (char *)Alloc((unsigned)n + 8);
    *owned = out;
    if (!out || !line) { Free(line); return text; }
    int m = 0, kept = 0;
    for (int at = 0; at <= n && kept < maxLines;) {
        int end = at;
        while (end < n && text[end] != '\n') ++end;
        int len = end - at;
        Copy(line, text + at, (unsigned)len);
        bool last = kept + 1 == maxLines && end < n;              // lines are dropped after this one
        if (last) { Copy(line + len, Ellipsis, 3); len += 3; }
        line[len] = 0;
        char *fitted;
        const char *shown = FitToRoom(line, impl, room, &fitted);
        int sl = (int)Len(shown);
        if (kept) out[m++] = '\n';
        Copy(out + m, shown, (unsigned)sl);
        m += sl;
        Free(fitted);
        ++kept;
        at = end + 1;
        if (end >= n) break;
    }
    out[m] = 0;
    Free(line);
    return out;
}

// Where and what DrawString draws so that nothing leaves the screen (see the top of this file).
static const char *OnScreen(void *window, void *impl, FontExtra *f, const char *text, int *x, int *y, char **owned) {
    *owned = 0;
    int sw, sh;
    if (!text || !*text || !ScreenSize(window, &sw, &sh)) return text;
    int n = (int)Len(text);
    if (!ClampWanted(text, n)) return text;                   // the stock game's own text: as before
    int width = Measure(impl, f, text, n, 1.0f);
    int lineH = *(int *)((char *)impl + 4), lines = 1;
    for (int i = 0; i < n; ++i) if (text[i] == '\n') ++lines;
    int h = lines * lineH;
    if (*x >= 0 && *x + width <= sw && *y >= 0 && *y + h <= sh) return text;     // on the screen: as before
    if (*x >= sw || *x + width <= 0 || *y >= sh || *y + h <= 0) return text;      // wholly off it: left alone
    int fitLines = lineH > 0 ? sh / lineH : lines;
    if (fitLines < 1) fitLines = 1;
    if (width > sw || lines > fitLines) {
        const char *original = text;
        text = CutLines(text, impl, sw, fitLines, owned);
        if (!*text) {                                   // not even "…" fits: the English line, when there is one
            HMODULE tr = GetModuleHandleW(L"vf1tr.dll");
            TrEnglishOfFn english = tr ? (TrEnglishOfFn)GetProcAddress(tr, "VF1Tr_EnglishOf") : 0;
            const char *e = english ? english(original) : 0;
            if (e && *e && e != original) text = e;
        }
        n = (int)Len(text);
        width = Measure(impl, f, text, n, 1.0f);
        lines = 1;
        for (int i = 0; i < n; ++i) if (text[i] == '\n') ++lines;
        h = lines * lineH;
    }
    if (*x < 0 || width > sw) *x = 0;
    else if (*x + width > sw) *x = sw - width;
    if (*y < 0 || h > sh) *y = 0;
    else if (*y + h > sh) *y = sh - h;
    return text;
}

// The word wrapper's box (x, y, width) moved so that its text ends at the screen's edge: the text is wrapped at the
// wrapper's own line breaks inside the box, so only the box moves.
static void WrapOnScreen(void *window, const char *text, int *x, int *y, int width, int height) {
    int sw, sh;
    void *impl = window ? *(void **)window : 0;
    if (!impl || !text || !*text || !ScreenSize(impl, &sw, &sh)) return;
    if (*x >= 0 && *x + width <= sw && *y >= 0 && *y + height <= sh) return;
    if (*x >= sw || *x + width <= 0 || *y >= sh || *y + height <= 0) return;
    if (*x < 0 || width > sw) *x = 0;
    else if (*x + width > sw) *x = sw - width;
    if (*y < 0 || height > sh) *y = 0;
    else if (*y + height > sh) *y = sh - height;
}
