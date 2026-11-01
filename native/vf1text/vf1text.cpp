// vf1text.dll -- Render Unicode with In-Game Fonts (Virtual Families 1 Fun Patcher).
//
// Installed in "<game>\Virtual Families 1 Patcher Files\" only while the setting is on; vf1fun.dll loads it and
// calls VF1Text_Startup() once, before theGame::Init. Everything is a jump at a function entry (VF1 has no
// ASLR), each checked against the stock bytes first; nothing of the game's art or saves is changed.
//
// Text: a game string is read by the patcher's one rule (patcher/vf1_text.py): valid UTF-8 is UTF-8, anything
// else is one character per byte (Windows-1252, its five unassigned bytes as Latin-1). It is drawn one whole
// character (grapheme cluster) at a time:
//   * the game's own letter: U+0020..U+007F and U+00A2..U+00FF, which every font sheet has, and the control
//     characters, which the game draws as its row 0 ("!"), exactly as the stock game does;
//   * else a patcher-made letter: "Unicode Text\<font>.png / .txt" beside this DLL (scripts/build_vf1_glyphs.py);
//   * else the letter drawn now by Windows in the font's style (glyph_gdi.inc, the same steps as
//     patcher/vf1_glyph_gdi.py), kept for the rest of the session;
//   * else the missing-letter box.
// Each letter is drawn as the game draws its own: the box clipped by ldwGameWindowImpl 0x407E60, then
// SDL_UpperBlit for a solid colour or BlitRectWithAlpha 0x404C30 for a see-through one, from a copy of the
// sheet tinted by ANDing every pixel with MapRGBA(r, g, b, 255) (0x402940), x moving on by the box's width
// plus the font's spacing.
//
// Hooked (function entries):
//   0x402320 ldwFont::GetWidth(text, scale)            -> FontGetWidth
//   0x409660 ldwGameWindowImpl::DrawString            -> DrawString
//   0x409450 ldwGameWindowImpl::DrawString(n bytes)   -> DrawStringN (word wrapping measures with it)
//   0x40D740 ldwTextControl::GetText(buffer, size)    -> GetText: never cuts inside a character
//   0x40DA70 ldwTextControlImpl::HandleMessage         -> TextMessage: types any character, deletes whole ones
//   0x4049BB the SDL_TEXTINPUT case of ldwGame's event loop (the stock game keeps only 1-byte text):
//            every character of the event is posted to the text box as (5, 0, 0x40000000 | code point).
//   0x40D370 ldwTextControlImpl::SetEditable          -> SetEditableHook: a name box takes VF1_NAME_LETTERS
//   0x40D430 ldwTextControlImpl::SetText               -> SetTextHook: a name box opens with the whole name
//   0x40D140 ldwTextControlImpl::Draw                  -> BoxDrawHook: a long name scrolls, never cut
//   0x409D70 the justified word wrapper                -> WrapHook: whole names for short forms
//   (names.inc: one character limit for every name box, the short forms and the Names files)
//
// The C runtime is not used (no CRT start-up runs under the tests' emulator): memory comes from the process
// heap, strings are walked by hand.
//
// Built a second time with VF1_FONT_MODE as vf1font.dll -- Use Unicode Font (overrides in-game fonts), the
// setting that cannot be on with Render Unicode with In-Game Fonts: the same hooks, typing and storage, but every
// letter, the game's own ones too, is drawn by Windows with the font chosen in the patcher (settings.ini
// [UnicodeFont] Face= and File=, Segoe UI when none), then Segoe UI and the fallback chain. Each game font keeps
// its height, baseline and weight; the size is fitted so that "The quick brown fox jumps over the lazy dog
// 0123456789" is as wide as the game font draws it, so layouts still fit (FitChosenFont, the same as
// patcher/vf1_game_fonts.fit_unicode_font). Its files are "Unicode Font\<font>.txt" (the styles).

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#ifdef VF1_FONT_MODE
static const bool FontMode = true;
#define SUB_FOLDER L"Unicode Font\\"
#else
static const bool FontMode = false;
#define SUB_FOLDER L"Unicode Text\\"
#endif

#include "extenders.inc"

// ================================================================ the game
struct SDL_PixelFormat {
    unsigned format;
    void *palette;
    unsigned char BitsPerPixel, BytesPerPixel, pad[2];
    unsigned Rmask, Gmask, Bmask, Amask;
};
struct SDL_Surface {
    unsigned flags;
    SDL_PixelFormat *format;
    int w, h, pitch;
    void *pixels;
};
struct SDL_Rect { int x, y, w, h; };
struct ldwRect { int left, top, right, bottom; };

typedef SDL_Surface *(__cdecl *IMG_LoadFn)(const char *);
typedef SDL_Surface *(__cdecl *CreateRGBSurfaceFn)(unsigned, int, int, int, unsigned, unsigned, unsigned, unsigned);
typedef unsigned (__cdecl *MapRGBAFn)(SDL_PixelFormat *, unsigned char, unsigned char, unsigned char, unsigned char);
typedef int (__cdecl *LockFn)(SDL_Surface *);
typedef void (__cdecl *UnlockFn)(SDL_Surface *);
typedef int (__cdecl *UpperBlitFn)(SDL_Surface *, const SDL_Rect *, SDL_Surface *, SDL_Rect *);

#define IAT(addr, type) (*(type *)(addr))
static const unsigned IAT_UpperBlit = 0x4B2244, IAT_MapRGBA = 0x4B22A0, IAT_Lock = 0x4B229C,
                      IAT_Unlock = 0x4B22A4, IAT_CreateRGBSurface = 0x4B2298, IAT_IMG_Load = 0x4B2300;

typedef bool (__thiscall *ClipFn)(void *window, ldwRect *rect, int *x, int *y);
typedef void (__thiscall *AlphaBlitFn)(void *window, SDL_Surface *, int x, int y, ldwRect rect, float alpha,
                                       float scale, bool);
typedef SDL_Surface *(__thiscall *TintFn)(void *impl, unsigned colour);
typedef bool (__thiscall *IsValidFn)(void *impl);
typedef void (__thiscall *SourceRectFn)(void *impl, int ch, ldwRect *rect);
typedef void *(__cdecl *MessagesFn)();
typedef void (__thiscall *PostFn)(void *messages, int message, int a, int b);
typedef void (__thiscall *PostChangedFn)(void *messages, int message, int a);
typedef void (__thiscall *EndEditFn)(void *control);

static const ClipFn Clip = (ClipFn)0x407E60;
static const AlphaBlitFn AlphaBlit = (AlphaBlitFn)0x404C30;
static const TintFn Tinted = (TintFn)0x402940;
static const MessagesFn Messages = (MessagesFn)0x402140;
static const PostFn Post = (PostFn)0x401E80;
static const PostChangedFn PostChanged = (PostChangedFn)0x401EA0;
static const EndEditFn EndEdit = (EndEditFn)0x40D4F0;
static const unsigned DefaultColour = 0x4E927C;     // the colour used when a colour's alpha is 0
static const int UnicodeKey = 0x40000000;           // a posted character that is a whole code point

// The four fonts' glyph tables (theStringManager 0x44FCC0; vf1_game_fonts.find_game_fonts).
struct KnownFont { unsigned table; const char *name; };
static const KnownFont Known[] = {
    { 0x4EB6F0, "SegoeUi33" }, { 0x4EC610, "SegoeUiBold17" }, { 0x4ED538, "SegoeUiBold18" },
    { 0x4EE460, "SegoeUiBold24" },
};

// ================================================================ small helpers (no C runtime)
static HMODULE ThisModule;
static HANDLE Heap;
static void *Alloc(unsigned n) {
    if (!Heap) Heap = GetProcessHeap();
    return HeapAlloc(Heap, HEAP_ZERO_MEMORY, n);
}
static void Free(void *p) { if (p) HeapFree(Heap, 0, p); }
static unsigned Len(const char *s) { unsigned n = 0; while (s[n]) ++n; return n; }
static unsigned WLen(const wchar_t *s) { unsigned n = 0; while (s[n]) ++n; return n; }
static void Copy(void *d, const void *s, unsigned n) {
    volatile unsigned char *dd = (volatile unsigned char *)d;
    const unsigned char *ss = (const unsigned char *)s;
    for (unsigned i = 0; i < n; ++i) dd[i] = ss[i];
}
static bool Same(const void *a, const void *b, unsigned n) {
    const unsigned char *x = (const unsigned char *)a, *y = (const unsigned char *)b;
    for (unsigned i = 0; i < n; ++i) if (x[i] != y[i]) return false;
    return true;
}
static bool SameNoCase(const wchar_t *a, const wchar_t *b) {
    for (;; ++a, ++b) {
        wchar_t x = *a, y = *b;
        if (x >= L'A' && x <= L'Z') x = (wchar_t)(x + 32);
        if (y >= L'A' && y <= L'Z') y = (wchar_t)(y + 32);
        if (x != y) return false;
        if (!x) return true;
    }
}

// ================================================================ the one text rule (patcher/vf1_text.py)
static const unsigned short Cp1252High[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152,
    0x008D, 0x017D, 0x008F, 0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122,
    0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178,
};

// One UTF-8 sequence at s (n bytes left): its code point and length, or length 0 when malformed.
static int Utf8At(const unsigned char *s, int n, unsigned *cp) {
    if (n <= 0) return 0;
    unsigned c = s[0];
    if (c < 0x80) { *cp = c; return 1; }
    int len; unsigned min;
    if (c >= 0xC2 && c <= 0xDF) { len = 2; c &= 0x1F; min = 0x80; }
    else if (c >= 0xE0 && c <= 0xEF) { len = 3; c &= 0x0F; min = 0x800; }
    else if (c >= 0xF0 && c <= 0xF4) { len = 4; c &= 0x07; min = 0x10000; }
    else return 0;
    if (n < len) return 0;
    for (int i = 1; i < len; ++i) {
        if ((s[i] & 0xC0) != 0x80) return 0;
        c = (c << 6) | (s[i] & 0x3F);
    }
    if (c < min || c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF)) return 0;
    *cp = c;
    return len;
}

static bool IsUtf8(const unsigned char *s, int n) {
    for (int i = 0; i < n;) {
        unsigned cp;
        int k = Utf8At(s + i, n - i, &cp);
        if (!k) return false;
        i += k;
    }
    return true;
}

static int Utf8Put(unsigned cp, unsigned char *out) {
    if (cp < 0x80) { out[0] = (unsigned char)cp; return 1; }
    if (cp < 0x800) { out[0] = (unsigned char)(0xC0 | (cp >> 6)); out[1] = (unsigned char)(0x80 | (cp & 0x3F)); return 2; }
    if (cp < 0x10000) {
        out[0] = (unsigned char)(0xE0 | (cp >> 12)); out[1] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F));
        out[2] = (unsigned char)(0x80 | (cp & 0x3F)); return 3;
    }
    out[0] = (unsigned char)(0xF0 | (cp >> 18)); out[1] = (unsigned char)(0x80 | ((cp >> 12) & 0x3F));
    out[2] = (unsigned char)(0x80 | ((cp >> 6) & 0x3F)); out[3] = (unsigned char)(0x80 | (cp & 0x3F));
    return 4;
}

static bool IsExtender(unsigned cp) {
    int lo = 0, hi = (int)(sizeof ExtenderRanges / sizeof ExtenderRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < ExtenderRanges[mid][0]) hi = mid - 1;
        else if (cp > ExtenderRanges[mid][1]) lo = mid + 1;
        else return true;
    }
    return false;
}
static bool Regional(unsigned cp) { return cp >= 0x1F1E6 && cp <= 0x1F1FF; }

// A string as code points, by the one rule. Returns the count; the caller gives room for n code points.
// utf8: -1 decides from these n bytes; 1 says the whole string they start is UTF-8 (the counted draw: a
// character cut by the count is left out, never read as single bytes); 0 reads single bytes.
static int Decode(const unsigned char *s, int n, unsigned *out, unsigned char *widths, int utf8 = -1) {
    int count = 0;
    if (utf8 < 0) utf8 = IsUtf8(s, n) ? 1 : 0;
    if (utf8) {
        for (int i = 0; i < n;) {
            unsigned cp;
            int k = Utf8At(s + i, n - i, &cp);
            if (!k) break;                        // only a cut last character
            out[count] = cp; widths[count] = (unsigned char)k; ++count;
            i += k;
        }
    } else {
        for (int i = 0; i < n; ++i) {
            unsigned b = s[i];
            out[count] = (b >= 0x80 && b < 0xA0) ? Cp1252High[b - 0x80] : b;
            widths[count] = 1;
            ++count;
        }
    }
    return count;
}

// Where the cluster starting at code point i ends (vf1_text.clusters).
static int ClusterEnd(const unsigned *cps, int n, int i) {
    int j = i + 1;
    if (Regional(cps[i]) && j < n && Regional(cps[j])) ++j;
    while (j < n) {
        unsigned cp = cps[j];
        if (cp == 0x200D) { ++j; if (j < n) ++j; continue; }
        if (IsExtender(cp)) { ++j; continue; }
        break;
    }
    return j;
}

// ================================================================ letters the patch adds
struct Page;
struct Extra {
    Extra *next;
    unsigned hash;
    unsigned keyLen;
    unsigned char key[32];            // the letter in UTF-8 (longer letters are not kept: drawn as the box)
    struct Sheet *sheet;              // the font sheet it is on (the patcher-made one or a page)
    int x, y, w;
};
struct TintList { TintList *next; unsigned colour; SDL_Surface *surface; };
struct Sheet { SDL_Surface *white; TintList *tints; int usedX, usedY; };

struct Style {
    wchar_t face[64];
    int weight, em, baseline;
    unsigned char lut[256];
    bool ok;
};

struct FontExtra {
    void *impl;                       // the ldwFontImpl this belongs to
    char name[32];
    int height;
    Style style;
    Sheet shipped;                    // the patcher-made sheet (may be empty)
    Sheet pages[16];                  // letters drawn this session, 1024 x 16 rows each
    int pageCount;
    Extra *buckets[512];
};
static FontExtra *Fonts[8];
static wchar_t Folder[MAX_PATH];      // ...\Virtual Families 1 Patcher Files\Unicode Text\ (with the slash)
static wchar_t PatcherFolder[MAX_PATH];   // ...\Virtual Families 1 Patcher Files\ (with the slash)
static char FolderUtf8[MAX_PATH * 3];

static unsigned Hash(const unsigned char *s, unsigned n) {
    unsigned h = 2166136261u;
    for (unsigned i = 0; i < n; ++i) { h ^= s[i]; h *= 16777619u; }
    return h;
}

static Extra *FindExtra(FontExtra *f, const unsigned char *key, unsigned n) {
    unsigned h = Hash(key, n);
    for (Extra *e = f->buckets[h & 511]; e; e = e->next)
        if (e->hash == h && e->keyLen == n && Same(e->key, key, n)) return e;
    return 0;
}

static Extra *AddExtra(FontExtra *f, const unsigned char *key, unsigned n) {
    if (n > sizeof ((Extra *)0)->key) return 0;
    Extra *e = (Extra *)Alloc(sizeof(Extra));
    if (!e) return 0;
    e->hash = Hash(key, n);
    e->keyLen = n;
    Copy(e->key, key, n);
    e->next = f->buckets[e->hash & 511];
    f->buckets[e->hash & 511] = e;
    return e;
}

#include "glyph_file.inc"
#include "glyph_gdi.inc"

// The tinted copy of a sheet (0x402940's rule: white is the sheet itself, else every pixel ANDed with
// MapRGBA(r, g, b, 255)), kept per colour.
static SDL_Surface *TintedSheet(Sheet *sheet, unsigned colour) {
    SDL_Surface *white = sheet->white;
    if (!white) return 0;
    unsigned char r = (unsigned char)colour, g = (unsigned char)(colour >> 8), b = (unsigned char)(colour >> 16);
    if (r == 0xFF && g == 0xFF && b == 0xFF) return white;
    for (TintList *t = sheet->tints; t; t = t->next)
        if ((t->colour & 0xFFFFFF) == (colour & 0xFFFFFF)) return t->surface;
    SDL_PixelFormat *fmt = white->format;
    SDL_Surface *s = IAT(IAT_CreateRGBSurface, CreateRGBSurfaceFn)(0, white->w, white->h, fmt->BitsPerPixel,
                                                                 fmt->Rmask, fmt->Gmask, fmt->Bmask, fmt->Amask);
    if (!s) return 0;
    unsigned mask = IAT(IAT_MapRGBA, MapRGBAFn)(s->format, r, g, b, 0xFF);
    IAT(IAT_Lock, LockFn)(s);
    IAT(IAT_Lock, LockFn)(white);
    for (int y = 0; y < white->h; ++y) {
        unsigned *src = (unsigned *)((unsigned char *)white->pixels + y * white->pitch);
        unsigned *dst = (unsigned *)((unsigned char *)s->pixels + y * s->pitch);
        for (int x = 0; x < white->w; ++x) dst[x] = src[x] & mask;
    }
    IAT(IAT_Unlock, UnlockFn)(white);
    IAT(IAT_Unlock, UnlockFn)(s);
    TintList *t = (TintList *)Alloc(sizeof(TintList));
    if (!t) return s;
    t->colour = colour;
    t->surface = s;
    t->next = sheet->tints;
    sheet->tints = t;
    return s;
}

static void FitChosenFont(FontExtra *f, void *impl);   // Use Unicode Font: below

static FontExtra *ExtraFor(void *impl) {
    for (int i = 0; i < 8; ++i)
        if (Fonts[i] && Fonts[i]->impl == impl) return Fonts[i];
    int slot = -1;
    for (int i = 0; i < 8; ++i) if (!Fonts[i]) { slot = i; break; }
    if (slot < 0) return 0;
    FontExtra *f = (FontExtra *)Alloc(sizeof(FontExtra));
    if (!f) return 0;
    f->impl = impl;
    f->height = *(int *)((char *)impl + 4);
    unsigned table = *(unsigned *)((char *)impl + 0x18);
    const char *name = "";
    for (unsigned i = 0; i < sizeof Known / sizeof Known[0]; ++i)
        if (Known[i].table == table) name = Known[i].name;
    Copy(f->name, name, Len(name) + 1);
    LoadGlyphFile(f);
    if (FontMode) FitChosenFont(f, impl);
    Fonts[slot] = f;
    return f;
}

// ================================================================ one letter
// What to draw for the letter cps[i..j): a byte the game draws itself (byte >= 0), or a patcher letter.
struct Letter { int byte; Extra *extra; };

static bool GameHasByte(void *impl, unsigned b) {
    // the font's 256-entry map (impl+0x1C) gives row 0 to a byte without a row; row 0 is "!" (0x21).
    int row = *(int *)((char *)impl + 0x1C + 4 * b);
    if (row != 0) return true;
    return b == 0x21;
}

static unsigned Compose(const unsigned *cps, int n);   // NFC of a short cluster, or 0

static Letter LetterFor(FontExtra *f, void *impl, const unsigned *cps, int i, int j) {
    Letter l = { -1, 0 };
    unsigned cp = cps[i];
    if (j - i > 1) {
        unsigned single = Compose(cps + i, j - i);
        if (single) { cp = single; j = i + 1; }
    }
    if (j - i == 1) {
        if (cp < 0x20 || (cp >= 0x80 && cp < 0xA0)) { l.byte = (int)cp; return l; }   // as the stock game
        // Use Unicode Font draws every letter with the chosen font, the game's own ones too
        if (!FontMode && cp < 0x100 && GameHasByte(impl, cp)) { l.byte = (int)cp; return l; }
    }
    unsigned char key[64];
    unsigned n = 0;
    if (j - i == 1) n = (unsigned)Utf8Put(cp, key);
    else for (int k = i; k < j && n + 4 <= sizeof key; ++k) n += (unsigned)Utf8Put(cps[k], key + n);
    if (!f) { l.byte = 0; return l; }
    Extra *e = FindExtra(f, key, n);
    if (!e) e = (j - i == 1) ? MakeLetter(f, &cp, 1, key, n) : MakeLetter(f, cps + i, j - i, key, n);
    if (!e) { l.byte = 0; return l; }
    l.extra = e;
    return l;
}

static unsigned Compose(const unsigned *cps, int n) {
    typedef int (WINAPI *NormalizeFn)(int, const wchar_t *, int, wchar_t *, int);
    static NormalizeFn normalize;
    static bool looked;
    if (!looked) {
        looked = true;
        HMODULE m = LoadLibraryW(L"normaliz.dll");
        if (m) normalize = (NormalizeFn)GetProcAddress(m, "NormalizeString");
    }
    if (!normalize || n > 8) return 0;
    wchar_t in[20], out[8];
    int k = 0;
    for (int i = 0; i < n; ++i) {
        if (cps[i] >= 0x10000) { in[k++] = (wchar_t)(0xD800 + ((cps[i] - 0x10000) >> 10)); in[k++] = (wchar_t)(0xDC00 + ((cps[i] - 0x10000) & 0x3FF)); }
        else in[k++] = (wchar_t)cps[i];
    }
    int got = normalize(1 /* NormalizationC */, in, k, out, 8);
    if (got == 1 && !(out[0] >= 0xD800 && out[0] <= 0xDFFF)) return out[0];
    if (got == 2 && out[0] >= 0xD800 && out[0] <= 0xDBFF) return 0x10000 + ((out[0] - 0xD800) << 10) + (out[1] - 0xDC00);
    return 0;
}

// ================================================================ the game's drawing, a letter at a time
static void *ImplOf(void *font) { return *(void **)((char *)font + 4); }

static bool ImplValid(void *impl) {
    return impl && (*(IsValidFn *)(*(void ***)impl))(impl);
}

static void SourceRect(void *impl, int byte, ldwRect *r) {
    SourceRectFn fn = ((SourceRectFn *)*(void ***)impl)[1];
    fn(impl, (int)(signed char)byte, r);
}

// ================================================================ Use Unicode Font
// The chosen font: settings.ini [UnicodeFont] Face= (Segoe UI when none), and File= a .ttf/.otf the patcher copied
// beside this DLL (loaded for this game only). Each game font keeps its height, baseline and weight; its em is
// fitted so that FitReference is as wide as the game font draws it, within 60% to 130% of the font's own em
// (patcher/vf1_game_fonts.fit_unicode_font, the same arithmetic).
static const char FitReference[] = "The quick brown fox jumps over the lazy dog 0123456789";
static wchar_t ChosenFace[64];

static void ReadChosenFont() {
    if (ChosenFace[0]) return;
    wchar_t ini[MAX_PATH];
    unsigned at = WLen(PatcherFolder);
    const wchar_t *name = L"settings.ini";
    if (at + 13 >= MAX_PATH) return;
    Copy(ini, PatcherFolder, at * 2);
    Copy(ini + at, name, (WLen(name) + 1) * 2);
    GetPrivateProfileStringW(L"UnicodeFont", L"Face", L"Segoe UI", ChosenFace, 64, ini);
    if (!ChosenFace[0]) Copy(ChosenFace, L"Segoe UI", 9 * 2);
    wchar_t file[MAX_PATH];
    GetPrivateProfileStringW(L"UnicodeFont", L"File", L"", file, MAX_PATH, ini);
    if (file[0]) {
        // only a plain file name in the patcher's "Unicode Font" folder
        bool plain = true;
        for (wchar_t *p = file; *p; ++p) if (*p == L'\\' || *p == L'/' || *p == L':') plain = false;
        unsigned fl = WLen(Folder), nl = WLen(file);
        if (plain && fl + nl < MAX_PATH) {
            wchar_t full[MAX_PATH];
            Copy(full, Folder, fl * 2);
            Copy(full + fl, file, (nl + 1) * 2);
            AddFontResourceExW(full, FR_PRIVATE, 0);
        }
    }
}

static int FaceWidth(const wchar_t *face, int em, int weight, const char *text) {
    GdiFace *g = FaceFor(face, em, weight);
    if (!g || !g->ok) return 0;
    wchar_t w[64];
    int n = 0;
    while (text[n] && n < 63) { w[n] = (wchar_t)(unsigned char)text[n]; ++n; }
    HGDIOBJ old = SelectObject(GlyphDC, g->font);
    SIZE size = { 0, 0 };
    GetTextExtentPoint32W(GlyphDC, w, n, &size);
    SelectObject(GlyphDC, old);
    return size.cx;
}

static void SourceRect(void *impl, int byte, ldwRect *r);

static void FitChosenFont(FontExtra *f, void *impl) {
    ReadChosenFont();
    unsigned n = WLen(ChosenFace);
    Copy(f->style.face, ChosenFace, (n + 1) * 2);
    int game = 0;
    for (const char *p = FitReference; *p; ++p) {
        ldwRect r;
        SourceRect(impl, (unsigned char)*p, &r);
        game += r.right - r.left;
    }
    int em0 = f->style.em;
    int width = FaceWidth(f->style.face, em0, f->style.weight, FitReference);
    if (width <= 0 || game <= 0) return;      // not installed: the chain draws it at the font's own size
    int em = (em0 * game * 2 + width) / (2 * width);
    int lo = em0 * 6 / 10, hi = em0 * 13 / 10;
    if (em < lo) em = lo;
    if (em > hi) em = hi;
    f->style.em = em;
}

struct Run {
    unsigned *cps;
    unsigned char *widths;
    int n;
    unsigned buf[256];
    unsigned char wbuf[256];
};

static bool DecodeRun(Run *run, const char *text, int bytes, int utf8 = -1) {
    run->cps = run->buf; run->widths = run->wbuf;
    if (bytes > 256) {
        run->cps = (unsigned *)Alloc(sizeof(unsigned) * bytes);
        run->widths = (unsigned char *)Alloc((unsigned)bytes);
        if (!run->cps || !run->widths) {
            Free(run->cps); Free(run->widths);
            run->cps = run->buf; run->widths = run->wbuf;     // FreeRun must not free them again
            return false;
        }
    }
    run->n = Decode((const unsigned char *)text, bytes, run->cps, run->widths, utf8);
    return true;
}
static void FreeRun(Run *run) {
    if (run->cps != run->buf) { Free(run->cps); Free(run->widths); }
}

// One letter's box: (sheet source rect, width). For a game byte the game's own GetCharSourceRect.
static void LetterBox(void *impl, const Letter &l, ldwRect *r) {
    if (l.extra) {
        r->left = l.extra->x; r->top = l.extra->y;
        r->right = l.extra->x + l.extra->w; r->bottom = l.extra->y + *(int *)((char *)impl + 4);
    } else {
        SourceRect(impl, l.byte, r);
    }
}

static void BlitLetter(void *window, SDL_Surface *surface, ldwRect rect, int x, int y, unsigned colour) {
    if (!surface) return;
    if (!Clip(window, &rect, &x, &y)) return;
    if ((colour >> 24) == 0xFF) {
        SDL_Rect src = { rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top };
        SDL_Rect dst = { x, y, src.w, src.h };
        IAT(IAT_UpperBlit, UpperBlitFn)(surface, &src, *(SDL_Surface **)((char *)window + 0x30), &dst);
    } else {
        float alpha = (float)((double)(colour >> 24) / 255.0);
        AlphaBlit(window, surface, x, y, rect, alpha, 1.0f, true);
    }
}

// Whole names for short forms (names.inc).
static const char *WithNames(const char *text, void *impl, char **owned);

// 0x409660 ldwGameWindowImpl::DrawString(text, x, y, colour, font), ret 0x14.
static void __fastcall DrawString(void *window, void *, const char *text, int x, int y, unsigned colour, void *font) {
    if (!font) font = *(void **)((char *)window + 0x5C);
    if (!font) return;
    void *impl = ImplOf(font);
    if (!impl || !*(void **)((char *)impl + 0xC)) return;
    int spacing = *(int *)((char *)impl + 8);
    if ((colour >> 24) == 0) colour = *(unsigned *)DefaultColour;
    SDL_Surface *game = Tinted(impl, colour);
    if (!game || !text) return;
    FontExtra *f = ExtraFor(impl);
    char *owned;
    text = WithNames(text, impl, &owned);
    Run run;
    if (!DecodeRun(&run, text, (int)Len(text))) { Free(owned); return; }
    int startX = x;
    for (int i = 0; i < run.n;) {
        int j = ClusterEnd(run.cps, run.n, i);
        if (run.cps[i] == '\n' && j == i + 1) {
            y += *(int *)((char *)impl + 4);   // GetHeight(NULL) 0x4023F0
            x = startX;
            i = j;
            continue;
        }
        Letter l = LetterFor(f, impl, run.cps, i, j);
        i = j;
        ldwRect r;
        LetterBox(impl, l, &r);
        int w = r.right - r.left;
        if (w == 0) continue;
        SDL_Surface *s = l.extra ? TintedSheet(l.extra->sheet, colour) : game;
        BlitLetter(window, s, r, x, y, colour);
        x += w + spacing;
    }
    FreeRun(&run);
    Free(owned);
}

// 0x409450: the same for the first `count` bytes; measureOnly draws nothing; returns the last line's width.
// A character that does not fit in `count` whole is not drawn (word wrapping never cuts one).
static int __fastcall DrawStringN(void *window, void *, const char *text, int count, int x, int y,
                                  bool measureOnly, unsigned colour, void *font) {
    if (!font) font = *(void **)((char *)window + 0x5C);
    if (!font) return 0;
    void *impl = ImplOf(font);
    if (!impl || !*(void **)((char *)impl + 0xC)) return 0;
    int spacing = *(int *)((char *)impl + 8);
    if ((colour >> 24) == 0) colour = *(unsigned *)DefaultColour;
    SDL_Surface *game = Tinted(impl, colour);
    if (!game) return 0;
    if (count <= 0 || !text) return 0;
    int bytes = 0;
    while (bytes < count && text[bytes]) ++bytes;
    FontExtra *f = ExtraFor(impl);
    Run run;
    // the rule is the whole string's (word wrapping hands over pieces of a longer string)
    if (!DecodeRun(&run, text, bytes, IsUtf8((const unsigned char *)text, (int)Len(text)) ? 1 : 0)) return 0;
    int startX = x;
    for (int i = 0; i < run.n;) {
        int j = ClusterEnd(run.cps, run.n, i);
        if (run.cps[i] == '\n' && j == i + 1) {
            y += *(int *)((char *)impl + 4);
            x = startX;
            i = j;
            continue;
        }
        Letter l = LetterFor(f, impl, run.cps, i, j);
        i = j;
        ldwRect r;
        LetterBox(impl, l, &r);
        int w = r.right - r.left;
        if (w == 0) continue;
        if (!measureOnly) {
            SDL_Surface *s = l.extra ? TintedSheet(l.extra->sheet, colour) : game;
            BlitLetter(window, s, r, x, y, colour);
        }
        x += w + spacing;
    }
    FreeRun(&run);
    return x - startX;
}

// The stock measure of `bytes` bytes of text, no names replaced: ldwFont::GetWidth's arithmetic.
static int Measure(void *impl, FontExtra *f, const char *text, int bytes, float scale) {
    int spacing = *(int *)((char *)impl + 8);
    Run run;
    if (!DecodeRun(&run, text, bytes)) return 0;
    int widest = 0, line = 0;
    for (int i = 0; i < run.n;) {
        int j = ClusterEnd(run.cps, run.n, i);
        if (run.cps[i] == '\n' && j == i + 1) {
            if (line && line > widest) widest = line;
            line = 0;
            i = j;
            continue;
        }
        Letter l = LetterFor(f, impl, run.cps, i, j);
        i = j;
        ldwRect r;
        LetterBox(impl, l, &r);
        line += (int)((double)(spacing - r.left + r.right) * (double)scale);
    }
    FreeRun(&run);
    if (line > widest) widest = line;
    if (widest) widest -= spacing;
    return widest;
}
static int MeasureRaw(void *impl, FontExtra *f, const char *text, int bytes) {
    return Measure(impl, f, text, bytes, 1.0f);
}

// 0x402320 ldwFont::GetWidth(text, scale), ret 8.
static int __fastcall FontGetWidth(void *font, void *, const char *text, float scale) {
    void *impl = ImplOf(font);
    if (!impl || !ImplValid(impl) || !text) return 0;
    FontExtra *f = ExtraFor(impl);
    char *owned;
    text = WithNames(text, impl, &owned);
    int w = Measure(impl, f, text, (int)Len(text), scale);
    Free(owned);
    return w;
}

// ================================================================ typing
// The bytes of the last whole character (cluster) of a valid UTF-8 string of n bytes.
static int LastCharBytes(const unsigned char *s, int n) {
    if (n <= 0) return 0;
    if (!IsUtf8(s, n)) return 1;
    Run run;
    if (!DecodeRun(&run, (const char *)s, n)) return 1;
    int start = 0, last = 0;
    for (int i = 0; i < run.n;) {
        int j = ClusterEnd(run.cps, run.n, i);
        int bytes = 0;
        for (int k = i; k < j; ++k) bytes += run.widths[k];
        last = bytes;
        start += bytes;
        i = j;
    }
    FreeRun(&run);
    return last ? last : 1;
}

// The longest start of s (n bytes) that fits in `room` bytes without cutting a character, when s is UTF-8.
static int FitBytes(const unsigned char *s, int n, int room) {
    if (n <= room) return n;
    if (!IsUtf8(s, n)) return room;
    Run run;
    if (!DecodeRun(&run, (const char *)s, n)) return room;
    int used = 0;
    for (int i = 0; i < run.n;) {
        int j = ClusterEnd(run.cps, run.n, i);
        int bytes = 0;
        for (int k = i; k < j; ++k) bytes += run.widths[k];
        if (used + bytes > room) break;
        used += bytes;
        i = j;
    }
    FreeRun(&run);
    return used;
}

struct TextControl {               // ldwTextControlImpl, the fields the stock handler uses
    unsigned char raw[0x38];
};
#define TC_I(c, off) (*(int *)((c)->raw + (off)))
#define TC_B(c, off) ((c)->raw[(off)])
#define TC_P(c, off) (*(char **)((c)->raw + (off)))

#include "names.inc"

// A name box takes a character while the text stays within VF1_NAME_LETTERS characters (and its bytes within the
// box's VF1_NAME_BOX_BYTES, checked by the caller).
static bool NameBoxTakes(TextControl *c, const char *buf, int len, const unsigned char *add, int n) {
    if (!IsNameBox(c)) return true;
    if (len + n > VF1_NAME_BOX_BYTES) return false;
    if (len + n <= VF1_NAME_LETTERS) return true;          // fewer bytes than the limit: fewer characters too
    char *t = (char *)Alloc((unsigned)(len + n + 1));
    if (!t) return false;
    Copy(t, buf, (unsigned)len);
    Copy(t + len, add, (unsigned)n);
    bool ok = !IsUtf8((const unsigned char *)t, len + n) ||
              ClusterCount((const unsigned char *)t, len + n) <= VF1_NAME_LETTERS;
    Free(t);
    return ok;
}

// 0x40DA70 ldwTextControlImpl::HandleMessage(message, a, b), ret 0xC: the stock rules, plus a whole code
// point posted as (5, 0, 0x40000000 | cp) is added in UTF-8 when it fits, and backspace deletes a whole
// character of a UTF-8 text.
static bool __fastcall TextMessage(TextControl *c, void *, int message, int a, int ch) {
    if (!TC_B(c, 0x25) || !*((char *)TC_P(c, 0x1C) + 8)) return false;
    if (message == 6) return a != 0x3E8;
    if (message != 5) return false;
    char *buf = TC_P(c, 0x30);
    int len = TC_B(c, 0x2F) ? TC_I(c, 0x34) : (int)Len(buf);
    if (ch == 8) {
        if (len > 0) {
            int drop = TC_B(c, 0x2F) ? 1 : LastCharBytes((unsigned char *)buf, len);
            buf[len - drop] = 0;
            PostChanged(Messages(), 0xC, TC_I(c, 4));
        }
        return true;
    }
    if (ch == 0xD || ch == 9) { EndEdit(c); return true; }
    if (len >= TC_I(c, 0x28)) return true;
    if (ch & UnicodeKey) {
        unsigned cp = (unsigned)ch & 0x1FFFFF;
        // a numbers-only box, a box in its other mode, or a control character: not typed
        if (TC_B(c, 0x2D) || TC_B(c, 0x2F) || cp < 0x20 || (cp >= 0x7F && cp < 0xA0) || cp > 0x10FFFF ||
            (cp >= 0xD800 && cp <= 0xDFFF))
            return true;
        unsigned char u[4];
        int n = Utf8Put(cp, u);
        if (len + n > TC_I(c, 0x28) || !NameBoxTakes(c, buf, len, u, n)) return true;
        Copy(buf + len, u, (unsigned)n);
        buf[len + n] = 0;
        PostChanged(Messages(), 0xC, TC_I(c, 4));
        return true;
    }
    bool numeric = TC_B(c, 0x2D) != 0;
    bool ok = (!numeric && ch > 0x1F && ch <= 0xFF) || (numeric && ch >= 0x30 && ch <= 0x39) || (len == 0 && ch == 0x2D);
    if (!ok) return true;
    unsigned char one = (unsigned char)ch;
    if (!NameBoxTakes(c, buf, len, &one, 1)) return true;
    buf[len] = (char)ch;
    buf[len + 1] = 0;
    PostChanged(Messages(), 0xC, TC_I(c, 4));
    return true;
}

// 0x40D740 ldwTextControl::GetText(buffer, size), ret 8: strncpy(buffer, text, size); buffer[size-1] = 0 --
// and never a piece of a character.
// A name box gives the game the short form of a longer name (names.inc ShortFor), recording the whole name in the
// Names file of the slot the call site writes to.
static void __fastcall GetText(void *control, void *, char *buffer, int size) {
    TextControl *box = *(TextControl **)((char *)control + 0x10);
    char *text = TC_P(box, 0x30);
    if (size <= 0) return;
    int n = (int)Len(text);
    if (IsNameBox(box) && !TC_B(box, 0x2F) && size - 1 < VF1_NAME_BOX_BYTES) {
        unsigned ret = (unsigned)(UINT_PTR)_ReturnAddress();
        int slot = 0;
        for (unsigned i = 0; i < sizeof NameSites / sizeof NameSites[0]; ++i)
            if (NameSites[i].ret == ret) slot = NameSites[i].slot < 0 ? CurrentSlot() : NameSites[i].slot;
        char out[VF1_NAME_BOX_BYTES + 1];
        int keep = ShortFor(text, n, size - 1, slot, out);
        int i = 0;
        for (; i < keep; ++i) buffer[i] = out[i];
        for (; i < size; ++i) buffer[i] = 0;
        return;
    }
    int keep = FitBytes((const unsigned char *)text, n, size - 1);
    int i = 0;
    for (; i < keep; ++i) buffer[i] = text[i];
    for (; i < size; ++i) buffer[i] = 0;          // strncpy pads with NULs
}

// The SDL_TEXTINPUT case: the event's text (UTF-8) at [esp+0x30]; eax = its length. 1 byte goes on as the
// stock game does (0x4049C4); anything longer is posted a character at a time here.
static void __cdecl PostTypedText(const char *text) {
    int n = (int)Len(text);
    for (int i = 0; i < n;) {
        unsigned cp;
        int k = Utf8At((const unsigned char *)text + i, n - i, &cp);
        if (!k) { ++i; continue; }
        i += k;
        if (cp < 0x20 || (cp >= 0x7F && cp < 0xA0)) continue;     // control characters are never typed
        Post(Messages(), 5, 0, cp < 0x80 ? (int)cp : (UnicodeKey | (int)cp));
    }
}

static const unsigned TextInputSite = 0x4049BB, TextInputOne = 0x4049C4, TextInputDone = 0x404A87;
__declspec(naked) static void TextInputDetour() {
    __asm {
        cmp eax, 1
        jne several
        push TextInputOne
        ret
    several:
        lea eax, [esp + 0x30]
        push eax
        call PostTypedText
        add esp, 4
        push TextInputDone
        ret
    }
}

// ================================================================ installing
static bool WriteCode(unsigned site, const unsigned char *bytes, int n) {
    DWORD old;
    if (!VirtualProtect((void *)site, (SIZE_T)n, PAGE_EXECUTE_READWRITE, &old)) return false;
    Copy((void *)site, bytes, (unsigned)n);
    VirtualProtect((void *)site, (SIZE_T)n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void *)site, (SIZE_T)n);
    return true;
}

struct Hook { unsigned site; unsigned char stock[9]; int n; void *target; };

extern "C" __declspec(dllexport) volatile unsigned VF1Text_Installed = 0;

extern "C" __declspec(dllexport) int __cdecl VF1Text_Startup() {
    static const Hook hooks[] = {
        { 0x402320, { 0x83, 0xEC, 0x10, 0x55, 0x8B, 0x69, 0x04 }, 7, (void *)&FontGetWidth },
        { 0x409660, { 0x83, 0xEC, 0x44, 0x8B, 0x44, 0x24, 0x58 }, 7, (void *)&DrawString },
        { 0x409450, { 0x83, 0xEC, 0x4C, 0x8B, 0x44, 0x24, 0x68 }, 7, (void *)&DrawStringN },
        { 0x40D740, { 0x8B, 0x41, 0x10, 0x8B, 0x48, 0x30, 0x56 }, 7, (void *)&GetText },
        { 0x40DA70, { 0x80, 0x79, 0x25, 0x00, 0x0F, 0x84, 0xD5, 0x00, 0x00 }, 9, (void *)&TextMessage },
        { TextInputSite, { 0x83, 0xF8, 0x01, 0x0F, 0x85, 0xC3, 0x00, 0x00, 0x00 }, 9, (void *)&TextInputDetour },
        // one character limit for every name box (names.inc)
        { 0x40D370, { 0x53, 0x8A, 0x5C, 0x24, 0x08 }, 5, (void *)&SetEditableHook },
        { 0x40D430, { 0x56, 0x8B, 0xF1, 0x8B, 0x46, 0x30 }, 6, (void *)&SetTextHook },
        { 0x40D140, { 0x83, 0xEC, 0x34, 0x56, 0x8B, 0xF1 }, 6, (void *)&BoxDrawHook },
        { 0x409D70, { 0x81, 0xEC, 0xDC, 0x04, 0x00, 0x00 }, 6, (void *)&WrapHook },
    };
    const int count = (int)(sizeof hooks / sizeof hooks[0]);
    // all or nothing: every site must hold the stock bytes
    for (int i = 0; i < count; ++i)
        if (!Same((void *)hooks[i].site, hooks[i].stock, (unsigned)hooks[i].n)) return 0;
    if (!FindFolder()) return 0;
    for (int i = 0; i < count; ++i) {
        unsigned char patch[16];
        patch[0] = 0xE9;
        *(int *)(patch + 1) = (int)((unsigned)hooks[i].target - (hooks[i].site + 5));
        for (int k = 5; k < hooks[i].n; ++k) patch[k] = 0x90;
        if (!WriteCode(hooks[i].site, patch, hooks[i].n)) return 0;
        VF1Text_Installed |= 1u << i;
    }
    return 1;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
