// vf1text.dll / vf1font.dll: colour emoji, drawn by DirectWrite and Direct2D -- the same steps as
// patcher/vf1_glyph_color.py (tests/test_colour_emoji.py runs this copy through 32-bit rundll32 and compares every
// pixel, and runs the game's drawing with it inside the emulator, VF1Text_ColourLetter carried out by the machine's
// real Direct2D).
//
// GDI draws in one colour. A whole character that is an emoji shown as a picture (emoji.inc, IsColourEmoji: the
// same rule as patcher/vf1_emoji.is_colour_emoji), or any character whose chain face is a colour font (COLR, CBDT,
// sbix or SVG: ColourFace, the shared Unicode spec's rule and Fish and Plant Tycoon's), is laid out by DirectWrite in
// that face (an emoji: the first colour font of the chain that has it, Segoe UI Emoji, then Noto Color Emoji; regular
// weight: a picture is never emboldened) at the font's em, and drawn by Direct2D with D2D1_DRAW_TEXT_OPTIONS_ENABLE_COLOR_FONT
// and grayscale anti-aliasing on a software DC render target bound to a 32-bit DIB the cell's height high: the
// layout's baseline on the font's baseline row, x = pad. Its box is the black-and-white letters' rule; its pixels
// are made straight (colour x 255 / alpha). It is kept only when it has colour (a flag's two letters, drawn in the
// brush's white, go to GDI and are tinted as any letter). It is kept on a colour page of the font that the game's tint never
// touches (Windows does not recolour emoji); a see-through colour still makes it see-through. Without Direct2D,
// DirectWrite or Segoe UI Emoji, or with settings.ini [UnicodeText] ColourEmoji=0, the character is drawn by GDI in
// black and white, as before.
//
// The factories, the software render target and the white brush are made once, at the first emoji (making the
// software render target loads Direct3D's WARP rasterizer, which takes a moment); each picture only binds the
// target to its own DIB.

#include <d2d1.h>
#include <dwrite.h>
#include "emoji.inc"

static const wchar_t EmojiFace[] = L"Segoe UI Emoji";

static bool IsEmojiPresentation(unsigned cp) {
    int lo = 0, hi = (int)(sizeof EmojiPresentationRanges / sizeof EmojiPresentationRanges[0]) - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        if (cp < EmojiPresentationRanges[mid][0]) hi = mid - 1;
        else if (cp > EmojiPresentationRanges[mid][1]) lo = mid + 1;
        else return true;
    }
    return false;
}

// One whole character (cps[0..n)) drawn as a colour picture: nothing in it asks for text presentation (U+FE0E), and
// a code point of it has Emoji_Presentation, or it holds U+FE0F, a keycap U+20E3, a skin tone or a tag character.
static bool IsColourEmoji(const unsigned *cps, int n) {
    for (int i = 0; i < n; ++i) if (cps[i] == 0xFE0E) return false;
    for (int i = 0; i < n; ++i) {
        unsigned cp = cps[i];
        if (IsEmojiPresentation(cp) || cp == 0xFE0F || cp == 0x20E3 || (cp >= 0x1F3FB && cp <= 0x1F3FF) ||
            (cp >= 0xE0020 && cp <= 0xE007F))
            return true;
    }
    return false;
}

// settings.ini [UnicodeText] ColourEmoji= (1 when absent): 0 keeps every emoji black and white.
static int ColourWanted = -1;
static bool WantColour() {
    if (ColourWanted < 0) {
        ColourWanted = 1;
        wchar_t ini[MAX_PATH], value[8];
        unsigned at = WLen(PatcherFolder);
        const wchar_t *name = L"settings.ini";
        if (at && at + 13 < MAX_PATH) {
            Copy(ini, PatcherFolder, at * 2);
            Copy(ini + at, name, (WLen(name) + 1) * 2);
            GetPrivateProfileStringW(L"UnicodeText", L"ColourEmoji", L"1", value, 8, ini);
            if (value[0] == L'0' && !value[1]) ColourWanted = 0;
        }
    }
    return ColourWanted != 0;
}

static ID2D1Factory *D2D;
static IDWriteFactory *DWrite;
static ID2D1DCRenderTarget *Target;
static ID2D1SolidColorBrush *Brush;
static bool ColourLooked;

static bool LoadColour() {
    if (!ColourLooked) {
        ColourLooked = true;
        typedef HRESULT (WINAPI *D2DCreateFn)(D2D1_FACTORY_TYPE, REFIID, const D2D1_FACTORY_OPTIONS *, void **);
        typedef HRESULT (WINAPI *DWCreateFn)(DWRITE_FACTORY_TYPE, REFIID, IUnknown **);
        HMODULE d2 = LoadLibraryExW(L"d2d1.dll", 0, 0x800 /* LOAD_LIBRARY_SEARCH_SYSTEM32 */);
        HMODULE dw = LoadLibraryExW(L"dwrite.dll", 0, 0x800);
        D2DCreateFn d2create = d2 ? (D2DCreateFn)GetProcAddress(d2, "D2D1CreateFactory") : 0;
        DWCreateFn dwcreate = dw ? (DWCreateFn)GetProcAddress(dw, "DWriteCreateFactory") : 0;
        void *f = 0;
        IUnknown *w = 0;
        ID2D1DCRenderTarget *target = 0;
        ID2D1SolidColorBrush *brush = 0;
        if (d2create && dwcreate &&
            SUCCEEDED(d2create(D2D1_FACTORY_TYPE_SINGLE_THREADED, __uuidof(ID2D1Factory), 0, &f)) && f &&
            SUCCEEDED(dwcreate(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), &w)) && w) {
            D2D1_RENDER_TARGET_PROPERTIES props;
            props.type = D2D1_RENDER_TARGET_TYPE_SOFTWARE;
            props.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
            props.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
            props.dpiX = 96.0f; props.dpiY = 96.0f;
            props.usage = D2D1_RENDER_TARGET_USAGE_NONE;
            props.minLevel = D2D1_FEATURE_LEVEL_DEFAULT;
            D2D1_COLOR_F white = { 1.0f, 1.0f, 1.0f, 1.0f };
            if (SUCCEEDED(((ID2D1Factory *)f)->CreateDCRenderTarget(&props, &target)) && target &&
                SUCCEEDED(target->CreateSolidColorBrush(&white, 0, &brush)) && brush) {
                D2D = (ID2D1Factory *)f;
                DWrite = (IDWriteFactory *)w;
                Target = target;
                Brush = brush;
                return true;
            }
        }
        if (brush) brush->Release();
        if (target) target->Release();
        if (f) ((IUnknown *)f)->Release();
        if (w) w->Release();
    }
    return Target != 0;
}

// `units` UTF-16 units of one whole character in colour: *outW by height pixels, straight R, G, B, A bytes (the caller
// frees them). 0 when Windows cannot draw it in colour. Exported so the tests' emulator can carry it out with the
// machine's real Direct2D (it is the only place the DLL uses it).
extern "C" __declspec(dllexport) __declspec(noinline) int __cdecl VF1Text_ColourLetter(
        const wchar_t *face, int weight, int em, int baseline, int height, const wchar_t *text, int units,
        unsigned char **out, int *outW) {
    *out = 0;
    *outW = 0;
    if (!LoadColour() || units <= 0 || em <= 0 || height <= 0) return 0;
    IDWriteTextFormat *format = 0;
    IDWriteTextLayout *layout = 0;
    HDC dc = 0;
    HBITMAP bmp = 0;
    HGDIOBJ old = 0;
    int ok = 0;
    unsigned char *px = 0;
    int width = 0, pad = height, advance = 0;
    for (;;) {                       // once: a failed step breaks out
        if (FAILED(DWrite->CreateTextFormat(face, 0, (DWRITE_FONT_WEIGHT)weight, DWRITE_FONT_STYLE_NORMAL,
                                            DWRITE_FONT_STRETCH_NORMAL, (FLOAT)em, L"en-us", &format)) || !format) break;
        format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
        if (FAILED(DWrite->CreateTextLayout(text, (UINT32)units, format, 4096.0f, (FLOAT)(height * 4), &layout)) ||
            !layout) break;
        DWRITE_TEXT_METRICS tm;
        if (FAILED(layout->GetMetrics(&tm))) break;
        DWRITE_LINE_METRICS lm;
        UINT32 lines = 0;
        if (FAILED(layout->GetLineMetrics(&lm, 1, &lines)) || lines < 1) break;
        advance = (int)(tm.widthIncludingTrailingWhitespace + 0.5f);
        width = advance + 2 * pad;
        dc = CreateCompatibleDC(0);
        if (!dc) break;
        BITMAPINFOHEADER info = { sizeof(BITMAPINFOHEADER), width, -height, 1, 32, BI_RGB, 0, 0, 0, 0, 0 };
        void *bits = 0;
        bmp = CreateDIBSection(dc, (BITMAPINFO *)&info, DIB_RGB_COLORS, &bits, 0, 0);
        if (!bmp || !bits) break;
        old = SelectObject(dc, bmp);
        px = (unsigned char *)bits;
        for (int i = 0; i < width * height * 4; ++i) px[i] = 0;
        RECT rect = { 0, 0, width, height };
        if (FAILED(Target->BindDC(dc, &rect))) break;
        Target->BeginDraw();
        Target->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
        D2D1_COLOR_F clear = { 0.0f, 0.0f, 0.0f, 0.0f };
        Target->Clear(&clear);
        D2D1_POINT_2F origin = { (FLOAT)pad, (FLOAT)baseline - lm.baseline };
        Target->DrawTextLayout(origin, layout, Brush, D2D1_DRAW_TEXT_OPTIONS_ENABLE_COLOR_FONT);
        if (FAILED(Target->EndDraw())) break;
        GdiFlush();
        // kept only when the drawing has colour (FP's raster_colour: white ink has B = G = R = A; any other colour is
        // the font's): a letter a colour font draws in the brush's one colour (a flag's two letters) is drawn by
        // GDI instead, so the game's colour tints it as any letter
        for (int i = 0; i < width * height * 4 && !ok; i += 4)
            if (px[i + 3] >= 16 && (px[i] + 16 < px[i + 3] || px[i + 1] + 16 < px[i + 3] || px[i + 2] + 16 < px[i + 3]))
                ok = 1;
        break;
    }
    if (ok) {
        // the box: the black-and-white letters' rule (glyph_gdi.inc DrawLetter)
        int first = width, last = -1;
        for (int x = 0; x < width; ++x)
            for (int y = 0; y < height; ++y)
                if (px[(y * width + x) * 4 + 3]) { if (x < first) first = x; last = x; break; }
        int left = last >= 0 ? (first < pad ? first : pad) : pad;
        int right = last >= 0 ? (pad + advance > last + 1 ? pad + advance : last + 1) : pad + advance;
        int w = right - left;
        unsigned char *rows = (unsigned char *)Alloc((unsigned)(w * height * 4 + 4));
        if (rows) {
            for (int y = 0; y < height; ++y)
                for (int x = 0; x < w; ++x) {
                    const unsigned char *s = px + (y * width + left + x) * 4;
                    unsigned char *d = rows + (y * w + x) * 4;
                    unsigned a = s[3];
                    if (!a) continue;
                    unsigned r = (s[2] * 255u + a / 2) / a, g = (s[1] * 255u + a / 2) / a, b = (s[0] * 255u + a / 2) / a;
                    d[0] = (unsigned char)(r > 255 ? 255 : r); d[1] = (unsigned char)(g > 255 ? 255 : g);
                    d[2] = (unsigned char)(b > 255 ? 255 : b); d[3] = (unsigned char)a;
                }
            *out = rows;
            *outW = w;
        } else {
            ok = 0;
        }
    }
    if (layout) layout->Release();
    if (format) format->Release();
    if (old) SelectObject(dc, old);
    if (bmp) DeleteObject(bmp);
    if (dc) DeleteDC(dc);
    return ok;
}

// Puts a colour picture (straight RGBA rows) on a colour page of the font (1024 x 16 bands, never tinted).
static Extra *PlaceColourLetter(FontExtra *f, const unsigned char *rows, int w, const unsigned char *key, unsigned n) {
    const int pageW = 1024, bands = 16;
    if (w > pageW) w = pageW;
    Sheet *page = f->colourPageCount ? &f->colourPages[f->colourPageCount - 1] : 0;
    if (page && page->usedX + w > pageW) { page->usedX = 0; page->usedY += f->height; }
    if (!page || page->usedY + f->height > f->height * bands) {
        if (f->colourPageCount >= 4) return 0;
        unsigned r, g, b, a;
        DefaultMasks(f, &r, &g, &b, &a);
        SDL_Surface *s = IAT(IAT_CreateRGBSurface, CreateRGBSurfaceFn)(0, pageW, f->height * bands, 32, r, g, b, a);
        if (!s) return 0;
        page = &f->colourPages[f->colourPageCount++];
        page->white = s;
        page->colour = true;
        page->usedX = page->usedY = 0;
    }
    int x0 = page->usedX, y0 = page->usedY;
    SDL_PixelFormat *fmt = page->white->format;
    int rs = Shift(fmt->Rmask), gs = Shift(fmt->Gmask), bs = Shift(fmt->Bmask), as = Shift(fmt->Amask);
    IAT(IAT_Lock, LockFn)(page->white);
    for (int y = 0; y < f->height; ++y) {
        unsigned *dst = (unsigned *)((unsigned char *)page->white->pixels + (y0 + y) * page->white->pitch) + x0;
        for (int x = 0; x < w; ++x) {
            const unsigned char *s = rows + (y * w + x) * 4;
            dst[x] = s[3] ? (((unsigned)s[0] << rs) & fmt->Rmask) | (((unsigned)s[1] << gs) & fmt->Gmask) |
                            (((unsigned)s[2] << bs) & fmt->Bmask) | (((unsigned)s[3] << as) & fmt->Amask) : 0;
        }
    }
    IAT(IAT_Unlock, UnlockFn)(page->white);
    page->usedX += w;
    Extra *e = AddExtra(f, key, n);
    if (!e) return 0;
    e->sheet = page;
    e->x = x0; e->y = y0; e->w = w;
    return e;
}

// The face a whole character is drawn in colour from (patcher/vf1_glyph_gdi.Renderer.colour_face_for: the same), or
// 0: an emoji (IsColourEmoji) from the first face of the chain that is a colour font and has it (Segoe UI Emoji, then
// Noto Color Emoji when installed), else Segoe UI Emoji; any other character from the face the chain picks for it
// when that face is a colour font (COLR, CBDT, sbix or SVG), as Fish and Plant Tycoon's DLL does.
static const wchar_t *ColourFace(const Style &s, const unsigned *cps, int n) {
    if (IsColourEmoji(cps, n)) {
        GdiFace *g = ChooseFace(s, cps, n, true);
        return g ? g->face : EmojiFace;
    }
    GdiFace *g = ChooseFace(s, cps, n);
    return g && g->colour ? g->face : 0;
}

// A colour picture on a colour page, or 0 (the caller then draws it black and white as before).
static Extra *MakeColourLetter(FontExtra *f, const unsigned *cps, int n, const unsigned char *key, unsigned keyLen) {
    if (!WantColour()) return 0;
    const wchar_t *face = ColourFace(f->style, cps, n);
    if (!face) return 0;
    wchar_t text[64];
    int units = 0;
    for (int i = 0; i < n && units < 60; ++i) {
        unsigned cp = cps[i];
        if (cp >= 0x10000) { text[units++] = (wchar_t)(0xD800 + ((cp - 0x10000) >> 10)); text[units++] = (wchar_t)(0xDC00 + ((cp - 0x10000) & 0x3FF)); }
        else text[units++] = (wchar_t)cp;
    }
    text[units] = 0;
    unsigned char *rows = 0;
    int w = 0;
    if (!VF1Text_ColourLetter(face, 400, f->style.em, f->style.baseline, f->height, text, units, &rows, &w) || !rows)
        return 0;
    Extra *e = w > 0 ? PlaceColourLetter(f, rows, w, key, keyLen) : 0;
    Free(rows);
    return e;
}

// For the tests: rundll32 vf1text.dll,VF1Text_TestColour <out file>|<face>|<weight>|<em>|<baseline>|<height>|<letters>
// where <letters> is one or more characters, each its code points in hex joined by "+", separated by "/". Writes
// for each in turn "w h drawn" and its straight RGBA rows (one process pays Direct2D's start-up once).
#pragma comment(linker, "/EXPORT:VF1Text_TestColourW=_VF1Text_TestColourW@16")
extern "C" __declspec(dllexport) void CALLBACK VF1Text_TestColourW(HWND, HINSTANCE, LPWSTR line, int) {
    wchar_t *field[7];
    int k = 0;
    while (*line == L' ' || *line == L'"') ++line;
    for (unsigned e = WLen(line); e > 0 && (line[e - 1] == L'"' || line[e - 1] == L' '); --e) line[e - 1] = 0;
    field[k++] = line;
    for (wchar_t *p = line; *p && k < 7; ++p) if (*p == L'|') { *p = 0; field[k++] = p + 1; }
    if (k < 7) return;
    auto num = [](const wchar_t *p) { int v = 0; while (*p >= L'0' && *p <= L'9') v = v * 10 + (*p++ - L'0'); return v; };
    HANDLE h = CreateFileW(field[0], GENERIC_WRITE, 0, 0, CREATE_ALWAYS, 0, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    int height = num(field[5]);
    for (wchar_t *p = field[6]; *p;) {
        wchar_t text[40];
        int units = 0;
        while (*p && *p != L'/' && units < 36) {
            unsigned v = 0;
            while ((*p >= L'0' && *p <= L'9') || (*p >= L'A' && *p <= L'F')) { v = v * 16 + (unsigned)(*p <= L'9' ? *p - L'0' : *p - L'A' + 10); ++p; }
            if (v >= 0x10000) { text[units++] = (wchar_t)(0xD800 + ((v - 0x10000) >> 10)); text[units++] = (wchar_t)(0xDC00 + ((v - 0x10000) & 0x3FF)); }
            else text[units++] = (wchar_t)v;
            if (*p == L'+') ++p; else break;
        }
        text[units] = 0;
        while (*p && *p != L'/') ++p;
        if (*p == L'/') ++p;
        unsigned char *rows = 0;
        int w = 0;
        int drawn = VF1Text_ColourLetter(field[1], num(field[2]), num(field[3]), num(field[4]), height, text, units, &rows, &w);
        DWORD wrote;
        int head[3] = { w, height, drawn };
        WriteFile(h, head, sizeof head, &wrote, 0);
        if (rows) WriteFile(h, rows, (DWORD)(w * height * 4), &wrote, 0);
        Free(rows);
    }
    CloseHandle(h);
}
