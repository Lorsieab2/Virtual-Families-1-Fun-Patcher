/* ----------------------------------------------------------------- nothing runs off the screen (screen_tr.inc)
   (included by vf1tr.c; native/vf1text/screen.inc is the same rule inside the Unicode DLLs, which do it themselves;
   tests/test_screen_edge.py)

   The owner, 2026-11-03: "i dont care if things run out of boxes, they just need to not run off the screen". With a
   translation chosen and neither Unicode DLL installed, a text the game draws (DrawString 0x409660: every left,
   right-aligned and centred draw and every text box ends there) or wraps (0x409D70) that would leave the screen, but
   is partly on it, is moved so that it ends at the screen's edge; one wider than the screen is cut, each line, to its
   longest start that fits with "..." (the stock fonts have no "..." letter of their own); one taller keeps the lines
   that fit, the last ending in "...". A text wholly off the screen is left as it is. Two jumps at the two functions'
   entries, written only when both entries hold their stock bytes; the stock code runs through two trampolines that
   are naked functions in this DLL's own code (executable, never data: DEP). */

typedef void (__fastcall *DrawStringFn)(void *window, void *edx, const char *text, int x, int y, unsigned colour,
                                        void *font);
typedef int (__fastcall *WrapFn)(void *outer, void *edx, const char *text, int x, int y, int width, unsigned colour,
                                 void *font, int measure);
typedef int (__fastcall *GetWidthFn)(void *font, void *edx, const char *text, float scale);

static const unsigned char STOCK_DRAW[7] = { 0x83, 0xEC, 0x44, 0x8B, 0x44, 0x24, 0x58 };   /* 0x409660 */
static const unsigned char STOCK_WRAP[6] = { 0x81, 0xEC, 0xDC, 0x04, 0x00, 0x00 };          /* 0x409D70 */
static int screen_edge = 0;                      /* the two jumps are in */

/* The stock DrawString and wrapper: their first instructions, then on at the next one. */
__declspec(naked) static void stock_draw_string(void) {
    __asm {
        sub esp, 0x44
        mov eax, dword ptr [esp + 0x58]
        push 0x409667
        ret
    }
}
__declspec(naked) static void stock_wrap(void) {
    __asm {
        sub esp, 0x4DC
        push 0x409D76
        ret
    }
}

static int screen_size(void *window, int *w, int *h) {
    const int *surface = window != NULL ? *(const int **)((char *)window + 0x30) : NULL;   /* SDL_Surface */
    if (surface == NULL || surface[2] <= 0 || surface[3] <= 0) return 0;
    *w = surface[2];
    *h = surface[3];
    return 1;
}

static int text_width(void *font, const char *text) {
    return ((GetWidthFn)(UINT_PTR)0x402320u)(font, NULL, text, 1.0f);
}

/* A line (len bytes) fitted into oom pixels into out: itself when it fits and no mark is wanted, else its longest
   start that fits with "..." (trailing spaces dropped); nothing when not even "..." fits. The text is Windows-1252,
   one byte a letter. Returns the bytes written. tmp has room for len + 4 bytes. */
static int fit_line(void *font, const char *line, int len, int room, int mark, char *tmp, char *out) {
    int keep;
    bcopy_(tmp, line, len);
    tmp[len] = 0;
    if (!mark && text_width(font, tmp) <= room) { bcopy_(out, line, len); return len; }
    for (keep = len; keep >= 0; --keep) {
        int k = keep;
        while (k > 0 && line[k - 1] == ' ') --k;
        bcopy_(tmp, line, k);
        tmp[k] = '.'; tmp[k + 1] = '.'; tmp[k + 2] = '.'; tmp[k + 3] = 0;
        if (text_width(font, tmp) <= room) { bcopy_(out, tmp, k + 3); return k + 3; }
    }
    return 0;
}

/* 	ext with each line no wider than oom and at most max_lines lines, the last kept one ending in "..." when
   lines were dropped; on the heap (*owned). */
static const char *cut_lines(void *font, const char *text, int room, int max_lines, char **owned) {
    int n = slen(text), m = 0, kept = 0, at = 0;
    char *out = (char *)tr_alloc((SIZE_T)n + 8), *tmp = (char *)tr_alloc((SIZE_T)n + 8);
    *owned = out;
    if (out == NULL || tmp == NULL) { if (tmp != NULL) HeapFree(GetProcessHeap(), 0, tmp); return text; }
    while (kept < max_lines) {
        int end = at;
        while (end < n && text[end] != '\n') ++end;
        if (kept) out[m++] = '\n';
        m += fit_line(font, text + at, end - at, room, kept + 1 == max_lines && end < n, tmp, out + m);
        ++kept;
        if (end >= n) break;
        at = end + 1;
    }
    out[m] = 0;
    HeapFree(GetProcessHeap(), 0, tmp);
    return out;
}

static int bytes_are(const unsigned char *at, const unsigned char *stock, int n) {
    int k;
    for (k = 0; k < n; ++k) if (at[k] != stock[k]) return 0;
    return 1;
}
static void __fastcall edge_draw_string(void *window, void *edx, const char *text, int x, int y, unsigned colour,
                                        void *font) {
    char *owned = NULL;
    void *f = font != NULL ? font : *(void **)((char *)window + 0x5C);
    int sw, sh;
    (void)edx;
    if (text != NULL && *text && f != NULL && screen_size(window, &sw, &sh)) {
        int n = slen(text), k, lines = 1, width = text_width(f, text);
        int line_h = *(int *)((char *)*(void **)((char *)f + 4) + 4), h;
        for (k = 0; k < n; ++k) if (text[k] == '\n') ++lines;
        h = lines * line_h;
        if (!(x >= 0 && x + width <= sw && y >= 0 && y + h <= sh) && !(x >= sw || x + width <= 0 || y >= sh || y + h <= 0)) {
            int fit = line_h > 0 ? sh / line_h : lines;
            if (fit < 1) fit = 1;
            if (width > sw || lines > fit) {
                text = cut_lines(f, text, sw, fit, &owned);
                width = text_width(f, text);
                lines = 1;
                for (k = 0; text[k]; ++k) if (text[k] == '\n') ++lines;
                h = lines * line_h;
            }
            if (x < 0 || width > sw) x = 0;
            else if (x + width > sw) x = sw - width;
            if (y < 0 || h > sh) y = 0;
            else if (y + h > sh) y = sh - h;
        }
    }
    ((DrawStringFn)(void *)stock_draw_string)(window, NULL, text, x, y, colour, font);
    if (owned != NULL) HeapFree(GetProcessHeap(), 0, owned);
}

static int __fastcall edge_wrap(void *outer, void *edx, const char *text, int x, int y, int width, unsigned colour,
                                void *font, int measure) {
    void *window = outer != NULL ? *(void **)outer : NULL;
    char *owned = NULL;
    int sw, sh, r;
    WrapFn wrap = (WrapFn)(void *)stock_wrap;
    (void)edx;
    if (!(measure & 0xFF) && text != NULL && *text && screen_size(window, &sw, &sh)) {
        int h = wrap(outer, NULL, text, x, y, width, colour, font, 1);
        if (!(x >= 0 && x + width <= sw && y >= 0 && y + h <= sh) && !(x >= sw || x + width <= 0 || y >= sh || y + h <= 0)) {
            if (h > sh) {          /* taller than the screen: its longest start that wraps, with "...", into it */
                int n = slen(text), lo = 0, hi = n;
                char *out = (char *)tr_alloc((SIZE_T)n + 8);
                if (out != NULL) {
                    while (lo < hi) {
                        int mid = (lo + hi + 1) / 2, k = mid;
                        while (k > 0 && (text[k - 1] == ' ' || text[k - 1] == '\n')) --k;
                        bcopy_(out, text, k);
                        out[k] = '.'; out[k + 1] = '.'; out[k + 2] = '.'; out[k + 3] = 0;
                        if (wrap(outer, NULL, out, 0, 0, width, colour, font, 1) <= sh) lo = mid; else hi = mid - 1;
                    }
                    while (lo > 0 && (text[lo - 1] == ' ' || text[lo - 1] == '\n')) --lo;
                    bcopy_(out, text, lo);
                    out[lo] = '.'; out[lo + 1] = '.'; out[lo + 2] = '.'; out[lo + 3] = 0;
                    owned = out;
                    text = out;
                    h = wrap(outer, NULL, text, x, y, width, colour, font, 1);
                }
            }
            if (x < 0 || width > sw) x = 0;
            else if (x + width > sw) x = sw - width;
            if (y < 0 || h > sh) y = 0;
            else if (y + h > sh) y = sh - h;
        }
    }
    r = wrap(outer, NULL, text, x, y, width, colour, font, measure);
    if (owned != NULL) HeapFree(GetProcessHeap(), 0, owned);
    return r;
}
static int jump_to(unsigned int at, void *target) {
    unsigned char jmp[5];
    DWORD rel = (DWORD)(UINT_PTR)target - (at + 5u);
    jmp[0] = 0xE9;
    jmp[1] = (unsigned char)rel; jmp[2] = (unsigned char)(rel >> 8);
    jmp[3] = (unsigned char)(rel >> 16); jmp[4] = (unsigned char)(rel >> 24);
    return write_code(at, jmp, 5);
}

/* Both entries must hold their stock bytes (a Unicode DLL has its own hooks there); else nothing is written. */
static void install_screen_edge(void) {
    if (!bytes_are((const unsigned char *)(UINT_PTR)0x409660u, STOCK_DRAW, sizeof STOCK_DRAW)
        || !bytes_are((const unsigned char *)(UINT_PTR)0x409D70u, STOCK_WRAP, sizeof STOCK_WRAP))
        return;
    if (jump_to(0x409660u, (void *)edge_draw_string) && jump_to(0x409D70u, (void *)edge_wrap)) screen_edge = 1;
}
