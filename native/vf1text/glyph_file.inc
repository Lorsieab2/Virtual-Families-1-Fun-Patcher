// vf1text.dll: the patcher-made letters, "Unicode Text\<font>.png" and "<font>.txt" beside this DLL
// (scripts/build_vf1_glyphs.py; the format is patcher/vf1_game_fonts.parse_glyph_file's).

static bool FindFolder() {
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(ThisModule, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return false;
    wchar_t *slash = 0;
    for (wchar_t *p = path; *p; ++p) if (*p == L'\\' || *p == L'/') slash = p;
    if (!slash) return false;
    slash[1] = 0;
    const wchar_t *sub = L"Unicode Text\\";
    unsigned at = WLen(path), sl = WLen(sub);
    if (at + sl + 64 >= MAX_PATH) return false;
    Copy(Folder, path, at * 2);
    Copy(Folder + at, sub, (sl + 1) * 2);
    int bytes = WideCharToMultiByte(CP_UTF8, 0, Folder, -1, FolderUtf8, (int)sizeof FolderUtf8, 0, 0);
    return bytes > 0;
}

static char *ReadWhole(const wchar_t *path, unsigned *size) {
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, 0, 0);
    if (h == INVALID_HANDLE_VALUE) return 0;
    DWORD hi = 0, lo = GetFileSize(h, &hi);
    char *data = 0;
    if (hi == 0 && lo < 8u * 1024 * 1024) {
        data = (char *)Alloc(lo + 1);
        DWORD got = 0;
        if (data && (!ReadFile(h, data, lo, &got, 0) || got != lo)) { Free(data); data = 0; }
        if (data) { data[lo] = 0; *size = lo; }
    }
    CloseHandle(h);
    return data;
}

static int Number(const char *&p) {
    while (*p == ' ' || *p == '\t') ++p;
    int sign = 1, v = 0;
    if (*p == '-') { sign = -1; ++p; }
    while (*p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    return sign * v;
}

static unsigned Hex(const char *&p) {
    unsigned v = 0;
    for (;;) {
        char c = *p;
        if (c >= '0' && c <= '9') v = v * 16 + (unsigned)(c - '0');
        else if (c >= 'A' && c <= 'F') v = v * 16 + (unsigned)(c - 'A' + 10);
        else if (c >= 'a' && c <= 'f') v = v * 16 + (unsigned)(c - 'a' + 10);
        else return v;
        ++p;
    }
}

static bool Starts(const char *p, const char *word) {
    while (*word) if (*p++ != *word++) return false;
    return *p == ' ' || *p == '\t';
}

// The masks of a 32-bit sheet with alpha (the shipped sheet's when it loaded, else RGBA in memory order).
static void DefaultMasks(FontExtra *f, unsigned *r, unsigned *g, unsigned *b, unsigned *a) {
    SDL_Surface *s = f->shipped.white;
    if (s && s->format->BytesPerPixel == 4 && s->format->Amask) {
        *r = s->format->Rmask; *g = s->format->Gmask; *b = s->format->Bmask; *a = s->format->Amask;
    } else {
        *r = 0x000000FF; *g = 0x0000FF00; *b = 0x00FF0000; *a = 0xFF000000;
    }
}

static void DefaultStyle(FontExtra *f) {
    const wchar_t *face = L"Segoe UI";
    Copy(f->style.face, face, (WLen(face) + 1) * 2);
    f->style.weight = 400;
    f->style.em = f->height * 3 / 4;
    f->style.baseline = f->height * 4 / 5;
    for (int i = 0; i < 256; ++i) f->style.lut[i] = (unsigned char)i;
    f->style.ok = true;
}

static void LoadGlyphFile(FontExtra *f) {
    DefaultStyle(f);
    if (!f->name[0]) return;
    wchar_t path[MAX_PATH];
    unsigned at = WLen(Folder), nl = Len(f->name);
    if (at + nl + 5 >= MAX_PATH) return;
    Copy(path, Folder, at * 2);
    for (unsigned i = 0; i < nl; ++i) path[at + i] = (wchar_t)(unsigned char)f->name[i];
    const wchar_t *ext = L".txt";
    Copy(path + at + nl, ext, 5 * 2);
    unsigned size = 0;
    char *text = ReadWhole(path, &size);
    if (!text) return;
    // the sheet
    char png[MAX_PATH * 3 + 40];
    unsigned fl = Len(FolderUtf8);
    if (fl + nl + 5 < sizeof png) {
        Copy(png, FolderUtf8, fl);
        Copy(png + fl, f->name, nl);
        Copy(png + fl + nl, ".png", 5);
        f->shipped.white = IAT(IAT_IMG_Load, IMG_LoadFn)(png);
    }
    if (f->shipped.white && (f->shipped.white->format->BytesPerPixel != 4 || !f->shipped.white->format->Amask))
        f->shipped.white = 0;     // only the 32-bit sheets build_vf1_glyphs.py writes
    const char *p = text;
    bool first = true;
    while (*p) {
        const char *line = p;
        while (*p && *p != '\n') ++p;
        const char *end = p;
        if (*p) ++p;
        if (first) {
            first = false;
            if (!(end - line >= 12 && Same(line, "vf1-glyphs 1", 12))) break;
            continue;
        }
        if (Starts(line, "baseline")) { line += 8; f->style.baseline = Number(line); }
        else if (Starts(line, "weight")) { line += 6; f->style.weight = Number(line); }
        else if (Starts(line, "em")) { line += 2; f->style.em = Number(line); }
        else if (Starts(line, "face")) {
            line += 5;
            int k = 0;
            while (line < end && *line != '\r' && k < 63) f->style.face[k++] = (wchar_t)(unsigned char)*line++;
            f->style.face[k] = 0;
        } else if (Starts(line, "lut")) {
            line += 3;
            for (int i = 0; i < 256; ++i) f->style.lut[i] = (unsigned char)Number(line);
        } else if (Starts(line, "g") && f->shipped.white) {
            line += 2;
            unsigned char key[64];
            unsigned n = 0;
            for (;;) {
                unsigned cp = Hex(line);
                if (n + 4 > sizeof key) break;
                n += (unsigned)Utf8Put(cp, key + n);
                if (*line != '+') break;
                ++line;
            }
            int x = Number(line), y = Number(line), w = Number(line);
            if (w > 0 && x >= 0 && y >= 0 && x + w <= f->shipped.white->w && y + f->height <= f->shipped.white->h &&
                !FindExtra(f, key, n)) {
                Extra *e = AddExtra(f, key, n);
                if (e) { e->sheet = &f->shipped; e->x = x; e->y = y; e->w = w; }
            }
        }
    }
    Free(text);
}
