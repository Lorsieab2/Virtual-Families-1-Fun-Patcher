// vf1text.dll: letters drawn by Windows in a font's style -- the same steps as patcher/vf1_glyph_gdi.py
// (tests/test_vf1_glyph_gdi.py runs this copy through 32-bit rundll32 and compares every pixel).

static const wchar_t *const FallbackFaces[] = {
    L"Segoe UI Historic", L"Segoe UI Symbol", L"Segoe UI Emoji",
    L"Yu Gothic", L"Microsoft YaHei", L"Malgun Gothic",
    L"Nirmala UI", L"Ebrima",
    L"Microsoft JhengHei", L"Leelawadee UI", L"Gadugi", L"Myanmar Text", L"Javanese Text", L"Mongolian Baiti",
    L"Microsoft Himalaya", L"Microsoft Yi Baiti", L"Microsoft New Tai Lue", L"Microsoft Tai Le",
    L"Microsoft PhagsPa", L"Sylfaen", L"Cambria Math",
    L"Noto Sans", L"Noto Sans Symbols", L"Noto Sans Symbols 2", L"Noto Sans CJK JP", L"Noto Sans Math",
};

struct GdiFace {
    GdiFace *next;
    wchar_t face[64];
    int em, weight;
    HFONT font;
    bool ok;
    unsigned char *cmap;
    unsigned cmapSize;
    unsigned sub12, sub4;     // offsets of the subtables used (0 = none)
};
static GdiFace *Faces;
static HDC GlyphDC;

static unsigned BE16(const unsigned char *p) { return (unsigned)(p[0] << 8 | p[1]); }
static unsigned BE32(const unsigned char *p) { return (unsigned)p[0] << 24 | (unsigned)p[1] << 16 | (unsigned)p[2] << 8 | p[3]; }

static void PickSubtables(GdiFace *g) {
    const unsigned char *t = g->cmap;
    unsigned size = g->cmapSize;
    g->sub12 = g->sub4 = 0;
    if (size < 4) return;
    unsigned count = BE16(t + 2);
    bool have12 = false, have4 = false;
    for (unsigned i = 0; i < count; ++i) {
        unsigned at = 4 + 8 * i;
        if (at + 8 > size) break;
        unsigned platform = BE16(t + at), encoding = BE16(t + at + 2), offset = BE32(t + at + 4);
        if (offset + 2 > size) continue;
        unsigned fmt = BE16(t + offset);
        bool unicodeSub = platform == 0 || (platform == 3 && (encoding == 1 || encoding == 10));
        if (!unicodeSub) continue;
        if (fmt == 12 && !have12) { g->sub12 = offset; have12 = true; }
        else if (fmt == 4 && !have4) { g->sub4 = offset; have4 = true; }
    }
    if (!have12) g->sub12 = 0xFFFFFFFF;
    if (!have4) g->sub4 = 0xFFFFFFFF;
}

static bool Covers(const GdiFace *g, unsigned cp) {
    const unsigned char *t = g->cmap;
    unsigned size = g->cmapSize;
    if (g->sub12 != 0xFFFFFFFF) {
        unsigned o = g->sub12;
        if (o + 16 > size) return false;
        unsigned n = BE32(t + o + 12);
        for (unsigned k = 0; k < n; ++k) {
            unsigned at = o + 16 + 12 * k;
            if (at + 12 > size) break;
            if (BE32(t + at) <= cp && cp <= BE32(t + at + 4)) return true;
        }
        return false;
    }
    if (g->sub4 != 0xFFFFFFFF) {
        if (cp > 0xFFFF) return false;
        unsigned o = g->sub4;
        if (o + 14 > size) return false;
        unsigned segx2 = BE16(t + o + 6), seg = segx2 / 2;
        unsigned ends = o + 14, starts = o + 16 + segx2, deltas = o + 16 + 2 * segx2, roffs = o + 16 + 3 * segx2;
        if (roffs + segx2 > size) return false;
        for (unsigned k = 0; k < seg; ++k) {
            if (cp <= BE16(t + ends + 2 * k)) {
                unsigned start = BE16(t + starts + 2 * k);
                if (cp < start) return false;
                int delta = (short)BE16(t + deltas + 2 * k);
                unsigned roff = BE16(t + roffs + 2 * k);
                unsigned gid;
                if (roff == 0) gid = (cp + (unsigned)delta) & 0xFFFF;
                else {
                    unsigned at = roffs + 2 * k + roff + 2 * (cp - start);
                    if (at + 2 > size) return false;
                    gid = BE16(t + at);
                    if (gid) gid = (gid + (unsigned)delta) & 0xFFFF;
                }
                return gid != 0;
            }
        }
    }
    return false;
}

static GdiFace *FaceFor(const wchar_t *face, int em, int weight) {
    for (GdiFace *g = Faces; g; g = g->next)
        if (g->em == em && g->weight == weight && SameNoCase(g->face, face)) return g;
    if (!GlyphDC) GlyphDC = CreateCompatibleDC(0);
    GdiFace *g = (GdiFace *)Alloc(sizeof(GdiFace));
    if (!g || !GlyphDC) return 0;
    unsigned n = WLen(face);
    if (n > 63) n = 63;
    Copy(g->face, face, n * 2);
    g->em = em; g->weight = weight;
    g->font = CreateFontW(-em, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET, OUT_TT_ONLY_PRECIS,
                          CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, 0, face);
    if (g->font) {
        HGDIOBJ old = SelectObject(GlyphDC, g->font);
        wchar_t got[64];
        if (GetTextFaceW(GlyphDC, 64, got) && SameNoCase(got, face)) {
            DWORD size = GetFontData(GlyphDC, 0x70616D63, 0, 0, 0);
            if (size != GDI_ERROR && size > 0 && size < 0x1000000) {
                g->cmap = (unsigned char *)Alloc(size);
                if (g->cmap && GetFontData(GlyphDC, 0x70616D63, 0, g->cmap, size) == size) {
                    g->cmapSize = size;
                    PickSubtables(g);
                    g->ok = true;
                }
            }
        }
        SelectObject(GlyphDC, old);
    }
    g->next = Faces;
    Faces = g;
    return g;
}

static bool NotNeeded(unsigned cp) {
    return cp == 0x200C || cp == 0x200D || (cp >= 0xFE00 && cp <= 0xFE0F) || (cp >= 0xE0000 && cp <= 0xE01EF);
}

static GdiFace *ChooseFace(const Style &s, const unsigned *cps, int n) {
    // the font's own face; with Use Unicode Font, the chosen font and then Segoe UI; then the chain
    for (int k = -2; k < (int)(sizeof FallbackFaces / sizeof FallbackFaces[0]); ++k) {
        const wchar_t *name = k == -2 ? s.face : k == -1 ? L"Segoe UI" : FallbackFaces[k];
        if (k == -1 && (!FontMode || SameNoCase(name, s.face))) continue;
        if (k >= 0 && SameNoCase(name, s.face)) continue;
        GdiFace *g = FaceFor(name, s.em, s.weight);
        if (!g || !g->ok) continue;
        bool all = true;
        for (int i = 0; i < n && all; ++i)
            if (!NotNeeded(cps[i]) && !Covers(g, cps[i])) all = false;
        if (all) return g;
    }
    return 0;
}

// The letter as coverage rows: *w by height, alpha bytes (caller frees). Returns false for the missing box.
static bool DrawLetter(const Style &s, int height, const unsigned *cps, int n, unsigned char **out, int *outW) {
    GdiFace *g = ChooseFace(s, cps, n);
    if (!g) return false;
    wchar_t text[64];
    int units = 0;
    for (int i = 0; i < n && units < 60; ++i) {
        unsigned cp = cps[i];
        if (cp >= 0x10000) { text[units++] = (wchar_t)(0xD800 + ((cp - 0x10000) >> 10)); text[units++] = (wchar_t)(0xDC00 + ((cp - 0x10000) & 0x3FF)); }
        else text[units++] = (wchar_t)cp;
    }
    text[units] = 0;
    int pad = height;
    HGDIOBJ old = SelectObject(GlyphDC, g->font);
    SIZE size = { 0, 0 };
    GetTextExtentPoint32W(GlyphDC, text, units, &size);
    TEXTMETRICW tm;
    GetTextMetricsW(GlyphDC, &tm);
    int advance = size.cx;
    int width = advance + 2 * pad;
    BITMAPINFOHEADER info = { sizeof(BITMAPINFOHEADER), width, -height, 1, 32, BI_RGB, 0, 0, 0, 0, 0 };
    void *bits = 0;
    HBITMAP bmp = CreateDIBSection(GlyphDC, (BITMAPINFO *)&info, DIB_RGB_COLORS, &bits, 0, 0);
    if (!bmp || !bits) { if (bmp) DeleteObject(bmp); SelectObject(GlyphDC, old); return false; }
    HGDIOBJ oldBmp = SelectObject(GlyphDC, bmp);
    unsigned char *px = (unsigned char *)bits;
    for (int i = 0; i < width * height * 4; ++i) px[i] = 0;
    SetBkMode(GlyphDC, TRANSPARENT);
    SetTextColor(GlyphDC, 0x00FFFFFF);
    TextOutW(GlyphDC, pad, s.baseline - tm.tmAscent, text, units);
    GdiFlush();
    int first = width, last = -1;
    for (int x = 0; x < width; ++x)
        for (int y = 0; y < height; ++y)
            if (px[(y * width + x) * 4 + 1]) { if (x < first) first = x; last = x; break; }
    int left = last >= 0 ? (first < pad ? first : pad) : pad;
    int right = last >= 0 ? (pad + advance > last + 1 ? pad + advance : last + 1) : pad + advance;
    int w = right - left;
    unsigned char *rows = (unsigned char *)Alloc((unsigned)(w * height + 1));
    if (rows)
        for (int y = 0; y < height; ++y)
            for (int x = 0; x < w; ++x)
                rows[y * w + x] = px[(y * width + left + x) * 4 + 1];
    SelectObject(GlyphDC, oldBmp);
    DeleteObject(bmp);
    SelectObject(GlyphDC, old);
    if (!rows) return false;
    *out = rows;
    *outW = w;
    return true;
}

// patcher/vf1_glyph_gdi.missing_box
static unsigned char *MissingBox(const Style &s, int height, int *outW) {
    int cap = (s.em * 7) / 10; if (cap < 3) cap = 3;
    int inner = s.em / 2; if (inner < 3) inner = 3;
    int w = inner + 2;
    int top = s.baseline - cap; if (top < 0) top = 0;
    int low = s.baseline < height ? s.baseline : height;
    if (low < top + 2) low = top + 2;
    int bottom = low - 1;
    unsigned char *rows = (unsigned char *)Alloc((unsigned)(w * height + 1));
    if (!rows) return 0;
    for (int y = top; y <= bottom && y < height; ++y)
        for (int x = 1; x < w - 1; ++x)
            if (y == top || y == bottom || x == 1 || x == w - 2) rows[y * w + x] = 0xFF;
    *outW = w;
    return rows;
}

static int Shift(unsigned mask) { int s = 0; if (!mask) return 0; while (!(mask & 1)) { mask >>= 1; ++s; } return s; }

// Puts coverage rows on a page of the font (1024 x 16 bands), the white sheet and every tinted copy.
static Extra *PlaceLetter(FontExtra *f, const unsigned char *rows, int w, const unsigned char *key, unsigned n, bool lut) {
    const int pageW = 1024, bands = 16;
    if (w > pageW) w = pageW;
    Sheet *page = f->pageCount ? &f->pages[f->pageCount - 1] : 0;
    if (page && page->usedX + w > pageW) { page->usedX = 0; page->usedY += f->height; }
    if (!page || page->usedY + f->height > f->height * bands) {
        if (f->pageCount >= 16) return 0;
        unsigned r, g, b, a;
        DefaultMasks(f, &r, &g, &b, &a);
        SDL_Surface *s = IAT(IAT_CreateRGBSurface, CreateRGBSurfaceFn)(0, pageW, f->height * bands, 32, r, g, b, a);
        if (!s) return 0;
        page = &f->pages[f->pageCount++];
        page->white = s;
        page->usedX = page->usedY = 0;
    }
    int x0 = page->usedX, y0 = page->usedY;
    SDL_PixelFormat *fmt = page->white->format;
    unsigned rgb = fmt->Rmask | fmt->Gmask | fmt->Bmask;
    int ashift = Shift(fmt->Amask);
    IAT(IAT_Lock, LockFn)(page->white);
    for (int y = 0; y < f->height; ++y) {
        unsigned *dst = (unsigned *)((unsigned char *)page->white->pixels + (y0 + y) * page->white->pitch) + x0;
        for (int x = 0; x < w; ++x) {
            unsigned av = rows[y * w + x];
            if (lut) av = f->style.lut[av];
            dst[x] = av ? (rgb | ((av << ashift) & fmt->Amask)) : 0;
        }
    }
    IAT(IAT_Unlock, UnlockFn)(page->white);
    for (TintList *t = page->tints; t; t = t->next) {
        unsigned mask = IAT(IAT_MapRGBA, MapRGBAFn)(t->surface->format, (unsigned char)t->colour,
                                                    (unsigned char)(t->colour >> 8), (unsigned char)(t->colour >> 16), 0xFF);
        IAT(IAT_Lock, LockFn)(t->surface);
        for (int y = 0; y < f->height; ++y) {
            unsigned *src = (unsigned *)((unsigned char *)page->white->pixels + (y0 + y) * page->white->pitch) + x0;
            unsigned *dst = (unsigned *)((unsigned char *)t->surface->pixels + (y0 + y) * t->surface->pitch) + x0;
            for (int x = 0; x < w; ++x) dst[x] = src[x] & mask;
        }
        IAT(IAT_Unlock, UnlockFn)(t->surface);
    }
    page->usedX += w;
    Extra *e = AddExtra(f, key, n);
    if (!e) return 0;
    e->sheet = page;
    e->x = x0; e->y = y0; e->w = w;
    return e;
}

static Extra *MakeLetter(FontExtra *f, const unsigned *use, int count, const unsigned char *key, unsigned keyLen) {
    unsigned char *rows = 0;
    int w = 0;
    bool drawn = DrawLetter(f->style, f->height, use, count, &rows, &w);
    if (!drawn) rows = MissingBox(f->style, f->height, &w);
    if (!rows) return 0;
    Extra *e = PlaceLetter(f, rows, w, key, keyLen, drawn);
    Free(rows);
    return e;
}

// For the tests: draws `letter` (UTF-8) in a style and writes "w h" and the coverage rows to a file.
#pragma comment(linker, "/EXPORT:VF1Text_TestLetterW=_VF1Text_TestLetterW@16")
// rundll32 vf1text.dll,VF1Text_TestLetter <out file>|<face>|<weight>|<em>|<baseline>|<height>|<letter hex cps, +>
extern "C" __declspec(dllexport) void CALLBACK VF1Text_TestLetterW(HWND, HINSTANCE, LPWSTR line, int) {
    wchar_t *field[7];
    int k = 0;
    while (*line == L' ' || *line == L'"') ++line;          // rundll32 hands over the quotes
    for (unsigned e = WLen(line); e > 0 && (line[e - 1] == L'"' || line[e - 1] == L' '); --e) line[e - 1] = 0;
    field[k++] = line;
    for (wchar_t *p = line; *p && k < 7; ++p) if (*p == L'|') { *p = 0; field[k++] = p + 1; }
    if (k < 7) return;
    Style s;
    unsigned fl = WLen(field[1]);
    if (fl > 63) fl = 63;
    Copy(s.face, field[1], fl * 2); s.face[fl] = 0;
    auto num = [](const wchar_t *p) { int v = 0; while (*p >= L'0' && *p <= L'9') v = v * 10 + (*p++ - L'0'); return v; };
    s.weight = num(field[2]); s.em = num(field[3]); s.baseline = num(field[4]);
    int height = num(field[5]);
    for (int i = 0; i < 256; ++i) s.lut[i] = (unsigned char)i;
    s.ok = true;
    unsigned cps[16];
    int n = 0;
    for (wchar_t *p = field[6]; *p && n < 16;) {
        unsigned v = 0;
        while ((*p >= L'0' && *p <= L'9') || (*p >= L'A' && *p <= L'F')) { v = v * 16 + (unsigned)(*p <= L'9' ? *p - L'0' : *p - L'A' + 10); ++p; }
        cps[n++] = v;
        if (*p == L'+') ++p; else break;
    }
    unsigned char *rows = 0;
    int w = 0;
    bool drawn = DrawLetter(s, height, cps, n, &rows, &w);
    if (!drawn) rows = MissingBox(s, height, &w);
    HANDLE h = CreateFileW(field[0], GENERIC_WRITE, 0, 0, CREATE_ALWAYS, 0, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD wrote;
    int head[3] = { w, height, drawn ? 1 : 0 };
    WriteFile(h, head, sizeof head, &wrote, 0);
    if (rows) WriteFile(h, rows, (DWORD)(w * height), &wrote, 0);
    CloseHandle(h);
    Free(rows);
}
