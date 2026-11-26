// vf1skin.dll -- "Skin Tones", the Virtual Families 1 Fun Patcher's companion for one feature. PROTOTYPE:
// the drawing part only (one tone drawn on one family member in the house). The tones' file, who gets
// which tone, Change Appearance and the log are the design's next steps (skin-tone-runtime-design.md).
//
// How the game draws a person (every step read from the vanilla executable): each sheet of people
// (heads, bodies, actions, sitting) is ONE picture kept in memory as an SDL surface, shared by everybody.
// Every draw of a cell ends in ldwGameWindowImpl::BlitRectWithAlpha 0x404C30 (surface, x, y, left, top,
// right, bottom, alpha, scale, centre), which reads the cell's rectangle from that surface.
//
// What this DLL does: while CVillagerManager::DrawVillager 0x48B4D0 draws a family member who has a tone,
// each blit from a sheet of people is given another surface instead: a copy of that ONE ROW of the sheet
// (one head, or one outfit) with its skin recoloured in the tone, made the first time it is needed and
// kept. The rectangle is moved up to the copy's only row; nothing else of the draw changes. The game's
// own surfaces, its files and every draw of a person with no tone are untouched.
//
// The recolour is the approved method (the workbench's vfskin.py), per skin pixel, in OKLCh: the tone's
// hue and chroma, the art's own shading kept as lightness offsets from the stock mid-skin, never ashy.
// What is skin comes from a mask picture per sheet ("Skin Masks\<sheet>.png" beside this DLL: a picture
// with a solid pixel where the sheet has skin and nothing else -- it holds no game art). A sheet whose
// mask is missing or is another size is drawn as the game draws it.
//
// The numbers of the tones are native/vf1skin/skin_tables.h (tools/vf1_skin_tables.py writes it).
// VF1 has no ASLR: the two addresses are fixed, and nothing is installed unless their bytes are the
// vanilla ones (all or nothing).

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "skin_tables.h"

// ---------------------------------------------------------------- the game
static const unsigned BlitSite = 0x404C30u;          // ldwGameWindowImpl::BlitRectWithAlpha
static const unsigned DrawVillagerSite = 0x48B4D0u;  // CVillagerManager::DrawVillager(slot, alpha)
static const unsigned GraphicsGet = 0x44F7C0u;       // theGraphicsManager::Get()
static const unsigned GetImageGrid = 0x44F5A0u;      // theGraphicsManager::GetImageGrid(EImage)
static const unsigned char BlitBytes[5] = { 0x83, 0xEC, 0x5C, 0xD9, 0xEE };                    // sub esp,5Ch; fldz
static const unsigned char DrawBytes[7] = { 0x83, 0xEC, 0x54, 0x8B, 0x44, 0x24, 0x58 };        // sub esp,54h; mov eax,[esp+58h]
enum { VILLAGER_SLOTS = 30 };

// SDL2's SDL_Surface and SDL_PixelFormat, as far as they are read here
struct SdlFormat { unsigned format; void *palette; unsigned char bits, bytes, pad[2]; unsigned r, g, b, a; };
struct SdlSurface { unsigned flags; SdlFormat *format; int w, h, pitch; void *pixels; };
typedef SdlSurface *(__cdecl *CreateSurfaceFn)(unsigned flags, int w, int h, int depth, unsigned r, unsigned g,
                                               unsigned b, unsigned a);
typedef void (__cdecl *FreeSurfaceFn)(SdlSurface *);
typedef SdlSurface *(__cdecl *LoadImageFn)(const char *path);
static CreateSurfaceFn CreateSurface;
static FreeSurfaceFn FreeSurface;
static LoadImageFn ReadPicture;

// ---------------------------------------------------------------- status
struct SkinStatus {
    unsigned magic, version;
    unsigned installed;      // 1 once both hooks are in
    unsigned sheets;         // sheets of people found in the game's memory
    unsigned masks;          // masks read
    unsigned rows;           // recoloured rows kept now
    unsigned bytes;          // their pixels' bytes
    unsigned swapped;        // blits given a recoloured row
    unsigned made;           // rows recoloured so far
};
extern "C" __declspec(dllexport) volatile SkinStatus VF1Skin_Status = { 0x4E4B3156u, 1u, 0, 0, 0, 0, 0, 0, 0 };

static HMODULE ThisModule;
static char MaskFolder[MAX_PATH * 3];

// ---------------------------------------------------------------- the sheets of people
// image: the game's EImage; part: which file of a grid made of two (heads: 00 young, 10 from age 45).
struct Sheet {
    unsigned image, part;
    const char *mask;
    SdlSurface *surface;     // the game's own surface
    int cellHeight;
    unsigned char *skin;     // one bit per pixel, row after row, or 0
    int triedMask;
};
static Sheet Sheets[] = {
    { 0x9C, 0, "female_heads00.png" }, { 0x9C, 1, "female_heads10.png" }, { 0x9D, 0, "female_bodies00.png" },
    { 0x9E, 0, "female_actions00.png" }, { 0x9F, 0, "female_sit00.png" },
    { 0xA0, 0, "male_heads00.png" }, { 0xA0, 1, "male_heads10.png" }, { 0xA1, 0, "male_bodies00.png" },
    { 0xA2, 0, "male_actions00.png" }, { 0xA3, 0, "male_sit00.png" },
};
enum { SHEET_COUNT = sizeof(Sheets) / sizeof(Sheets[0]) };
static int SheetsFound;

static void FindSheets() {
    if (SheetsFound) return;
    SheetsFound = 1;
    void *manager = ((void *(__cdecl *)())GraphicsGet)();
    if (!manager) return;
    unsigned found = 0;
    for (int i = 0; i < SHEET_COUNT; ++i) {
        Sheet &s = Sheets[i];
        unsigned char *grid = ((unsigned char *(__thiscall *)(void *, unsigned))GetImageGrid)(manager, s.image);
        if (!grid) continue;
        void ***parts = *(void ****)(grid + 0x30);          // the files of a grid made of several, or 0
        void **holder = parts ? parts[s.part] : (s.part == 0 ? *(void ***)(grid + 4) : 0);
        if (!holder || !*holder) continue;
        s.surface = (SdlSurface *)*holder;
        s.cellHeight = *(int *)(grid + 0x14);
        if (s.cellHeight <= 0 || s.surface->format->bytes != 4) { s.surface = 0; continue; }
        ++found;
    }
    VF1Skin_Status.sheets = found;
}

static unsigned Shift(unsigned mask) {
    unsigned n = 0;
    while (mask && !(mask & 1)) { mask >>= 1; ++n; }
    return n;
}

// The mask picture of a sheet -> one bit per pixel. A pixel is skin where the mask is solid.
static void ReadMask(Sheet &s) {
    if (s.triedMask) return;
    s.triedMask = 1;
    char path[sizeof(MaskFolder) + 64];
    unsigned n = 0;
    for (const char *p = MaskFolder; *p; ++p) path[n++] = *p;
    for (const char *p = s.mask; *p; ++p) path[n++] = *p;
    path[n] = 0;
    SdlSurface *m = ReadPicture(path);
    if (!m) return;
    if (m->w == s.surface->w && m->h == s.surface->h && m->format->bytes == 4 && m->format->a) {
        unsigned size = (unsigned)((m->w + 7) / 8) * (unsigned)m->h;
        unsigned char *bits = (unsigned char *)VirtualAlloc(0, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (bits) {
            unsigned shift = Shift(m->format->a), stride = (unsigned)(m->w + 7) / 8;
            for (int y = 0; y < m->h; ++y) {
                const unsigned *row = (const unsigned *)((const unsigned char *)m->pixels + y * m->pitch);
                unsigned char *out = bits + y * stride;
                for (int x = 0; x < m->w; ++x)
                    if (((row[x] >> shift) & 0xFF) >= 128) out[x >> 3] |= (unsigned char)(1 << (x & 7));
            }
            s.skin = bits;
            ++VF1Skin_Status.masks;
        }
    }
    FreeSurface(m);
}

// ---------------------------------------------------------------- the recolour (vfskin.recolour, one pixel)
static double CubeRoot(double v) {
    if (v <= 0) return 0;
    double x = v < 0.008 ? 0.2 : (v < 0.125 ? 0.4 : 0.8);
    for (int i = 0; i < 40; ++i) {
        double next = x - (x * x * x - v) / (3 * x * x);
        if (next == x) break;
        x = next;
    }
    return x;
}

static bool Linear(double L, double chroma, const SkinTone &t, double out[3]) {
    const double lab[3] = { L, chroma * t.cosHue, chroma * t.sinHue };
    double lms[3];
    for (int i = 0; i < 3; ++i) {
        double v = SkinLabToLms[i][0] * lab[0] + SkinLabToLms[i][1] * lab[1] + SkinLabToLms[i][2] * lab[2];
        lms[i] = v * v * v;
    }
    bool inside = true;
    for (int i = 0; i < 3; ++i) {
        out[i] = SkinLmsToLinear[i][0] * lms[0] + SkinLmsToLinear[i][1] * lms[1] + SkinLmsToLinear[i][2] * lms[2];
        if (out[i] < -1e-4 || out[i] > 1 + 1e-4) inside = false;
    }
    return inside;
}

static unsigned Stored(double light) {
    unsigned lo = 0, hi = 255;                 // how many of SkinEncode are not above the light
    while (lo < hi) {
        unsigned mid = (lo + hi) / 2;
        if (SkinEncode[mid] <= light) lo = mid + 1; else hi = mid;
    }
    return lo;
}

// (r, g, b) of the game's skin pixel -> the tone's, packed r | g << 8 | b << 16
static unsigned Recolour(unsigned r, unsigned g, unsigned b, const SkinTone &t) {
    const double lin[3] = { SkinLinear[r], SkinLinear[g], SkinLinear[b] };
    double L = 0;
    for (int i = 0; i < 3; ++i)
        L += SkinToLab[0][i] * CubeRoot(SkinToLms[i][0] * lin[0] + SkinToLms[i][1] * lin[1] + SkinToLms[i][2] * lin[2]);
    if (L > SkinKnee) L = SkinKnee + (L - SkinKnee) * SkinKeep;
    const double offset = L - SkinMid;
    double light = t.L + (offset < 0 ? offset * t.down : offset * t.up);
    if (light < SkinFloor) light = SkinFloor;
    if (light > SkinCeil) light = SkinCeil;
    double depth = -offset / SkinDown;
    if (depth < 0) depth = 0;
    if (depth > 1) depth = 1;
    double chroma = t.chroma * (1 + SkinShadowChroma * depth);
    double out[3];
    if (!Linear(light, chroma, t, out)) {
        chroma = t.chroma;                         // first give up a shadow's extra richness
        if (!Linear(light, chroma, t, out)) {      // then the lightness gives way toward the tone's own
            double far_ = light, near_ = t.L;
            for (int i = 0; i < 12; ++i) {
                double mid = (far_ + near_) / 2;
                if (Linear(mid, chroma, t, out)) near_ = mid; else far_ = mid;
            }
            Linear(near_, chroma, t, out);
        }
    }
    unsigned v[3];
    for (int i = 0; i < 3; ++i) v[i] = Stored(out[i] < 0 ? 0 : (out[i] > 1 ? 1 : out[i]));
    return v[0] | v[1] << 8 | v[2] << 16;
}

// A tone's answers are kept by colour: a sheet's skin is a few thousand colours used over and over.
struct Memo { unsigned key, value; };
enum { MEMO_SIZE = 4096 };
static Memo Memos[SKIN_TONE_COUNT + 1][MEMO_SIZE];

static unsigned RecolourKept(unsigned r, unsigned g, unsigned b, unsigned tone) {
    unsigned key = (r | g << 8 | b << 16) + 1;
    Memo &m = Memos[tone][(key * 2654435761u) >> 20];
    if (m.key != key) { m.value = Recolour(r, g, b, SkinTones[tone]); m.key = key; }
    return m.value;
}

// ---------------------------------------------------------------- the recoloured rows
struct Row { SdlSurface *surface; unsigned short sheet, row; unsigned char tone; unsigned used; };
enum { ROW_COUNT = 1024, ROW_BYTES_MOST = 96u << 20 };
static Row Rows[ROW_COUNT];
static unsigned RowClock, RowBytes;

static unsigned RowSize(const SdlSurface *s) { return (unsigned)s->pitch * (unsigned)s->h; }

static void DropOldest(const Row *keep) {
    Row *oldest = 0;
    for (int i = 0; i < ROW_COUNT; ++i)
        if (Rows[i].surface && &Rows[i] != keep && (!oldest || Rows[i].used < oldest->used)) oldest = &Rows[i];
    if (!oldest) return;
    RowBytes -= RowSize(oldest->surface);
    FreeSurface(oldest->surface);
    oldest->surface = 0;
    --VF1Skin_Status.rows;
}

static SdlSurface *MakeRow(const Sheet &s, int row, unsigned tone) {
    const SdlSurface *from = s.surface;
    const SdlFormat *f = from->format;
    SdlSurface *made = CreateSurface(0, from->w, s.cellHeight, 32, f->r, f->g, f->b, f->a);
    if (!made) return 0;
    const unsigned rs = Shift(f->r), gs = Shift(f->g), bs = Shift(f->b), as = Shift(f->a);
    const unsigned keep = ~(f->r | f->g | f->b);
    const unsigned stride = (unsigned)(from->w + 7) / 8;
    for (int y = 0; y < s.cellHeight; ++y) {
        const int sy = row * s.cellHeight + y;
        const unsigned *in = (const unsigned *)((const unsigned char *)from->pixels + sy * from->pitch);
        unsigned *out = (unsigned *)((unsigned char *)made->pixels + y * made->pitch);
        const unsigned char *skin = s.skin + sy * stride;
        for (int x = 0; x < from->w; ++x) {
            unsigned p = in[x];
            if ((skin[x >> 3] >> (x & 7)) & 1 && (!f->a || (p >> as) & 0xFF)) {
                unsigned c = RecolourKept((p >> rs) & 0xFF, (p >> gs) & 0xFF, (p >> bs) & 0xFF, tone);
                p = (p & keep) | (c & 0xFF) << rs | ((c >> 8) & 0xFF) << gs | ((c >> 16) & 0xFF) << bs;
            }
            out[x] = p;
        }
    }
    ++VF1Skin_Status.made;
    return made;
}

static SdlSurface *RowFor(int sheet, int row, unsigned tone) {
    unsigned at = ((unsigned)sheet * 131u + (unsigned)row * 11u + tone) % ROW_COUNT;
    Row *free_ = 0;
    for (int probe = 0; probe < ROW_COUNT; ++probe) {
        Row &r = Rows[(at + probe) % ROW_COUNT];
        if (r.surface && r.sheet == sheet && r.row == row && r.tone == tone) { r.used = ++RowClock; return r.surface; }
        if (!r.surface && !free_) free_ = &r;
    }
    if (!free_) { DropOldest(0); return 0; }       // full: this draw is the game's own, the next finds room
    SdlSurface *made = MakeRow(Sheets[sheet], row, tone);
    if (!made) return 0;
    free_->surface = made;
    free_->sheet = (unsigned short)sheet;
    free_->row = (unsigned short)row;
    free_->tone = (unsigned char)tone;
    free_->used = ++RowClock;
    RowBytes += RowSize(made);
    ++VF1Skin_Status.rows;
    while (RowBytes > ROW_BYTES_MOST) DropOldest(free_);
    VF1Skin_Status.bytes = RowBytes;
    return made;
}

// ---------------------------------------------------------------- the two hooks
static unsigned char Tones[VILLAGER_SLOTS];       // PROTOTYPE: the tone of each villager slot (the design: a file)
static volatile unsigned CurrentTone;             // the tone of the person being drawn, 0 for none
static unsigned SavedReturn;
static unsigned char Trampolines[32];             // made executable in Startup
static void *BlitOriginal, *DrawOriginal;

struct BlitArgs { SdlSurface *surface; int x, y, left, top, right, bottom; };

static void __cdecl SwapBlit(BlitArgs *a) {
    const unsigned tone = CurrentTone;
    if (!tone || tone > SKIN_TONE_COUNT || !a->surface) return;
    FindSheets();
    for (int i = 0; i < SHEET_COUNT; ++i) {
        Sheet &s = Sheets[i];
        if (s.surface != a->surface) continue;
        ReadMask(s);
        if (!s.skin || a->top < 0 || a->bottom > s.surface->h) return;
        const int row = a->top / s.cellHeight;
        if (a->bottom > (row + 1) * s.cellHeight) return;      // more than one row: not a cell
        SdlSurface *made = RowFor(i, row, tone);
        if (!made) return;
        a->surface = made;
        a->top -= row * s.cellHeight;
        a->bottom -= row * s.cellHeight;
        ++VF1Skin_Status.swapped;
        return;
    }
}

static void __cdecl BeginVillager(int slot) {
    CurrentTone = slot >= 0 && slot < VILLAGER_SLOTS ? Tones[slot] : 0;
}

static __declspec(naked) void BlitHook() {
    __asm {
        cmp dword ptr [CurrentTone], 0
        je go
        pushad
        lea eax, [esp + 24h]          // the first argument: 20h of registers, then the return address
        push eax
        call SwapBlit
        add esp, 4
        popad
    go:
        jmp dword ptr [BlitOriginal]
    }
}

static __declspec(naked) void DrawVillagerHook() {
    __asm {
        mov eax, [esp + 4]
        push ecx
        push eax
        call BeginVillager
        add esp, 4
        pop ecx
        mov eax, [esp]
        mov dword ptr [SavedReturn], eax
        mov dword ptr [esp], offset after
        jmp dword ptr [DrawOriginal]
    after:
        mov dword ptr [CurrentTone], 0
        jmp dword ptr [SavedReturn]
    }
}

static void Copy(void *dst, const void *src, unsigned n) {
    volatile unsigned char *d = (volatile unsigned char *)dst;
    const volatile unsigned char *s = (const volatile unsigned char *)src;
    for (unsigned i = 0; i < n; ++i) d[i] = s[i];
}

static bool Same(unsigned va, const unsigned char *bytes, unsigned n) {
    for (unsigned i = 0; i < n; ++i) if (((const unsigned char *)va)[i] != bytes[i]) return false;
    return true;
}

// stolen bytes + jmp back, at `at`; returns its size
static unsigned Trampoline(unsigned char *at, unsigned site, unsigned n) {
    Copy(at, (const void *)site, n);
    at[n] = 0xE9;
    int rel = (int)(site + n) - (int)((unsigned)at + n + 5);
    Copy(at + n + 1, &rel, 4);
    return n + 5;
}

static bool Jump(unsigned site, void *to, unsigned n) {
    DWORD old = 0, ignored = 0;
    if (!VirtualProtect((void *)site, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    unsigned char code[8];
    code[0] = 0xE9;
    int rel = (int)(unsigned)to - (int)(site + 5);
    Copy(code + 1, &rel, 4);
    for (unsigned i = 5; i < n; ++i) code[i] = 0x90;
    Copy((void *)site, code, n);
    VirtualProtect((void *)site, n, old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), (void *)site, n);
    return true;
}

extern "C" __declspec(dllexport) int __cdecl VF1Skin_Startup() {
    if (VF1Skin_Status.installed) return 1;
    if (!Same(BlitSite, BlitBytes, sizeof BlitBytes) || !Same(DrawVillagerSite, DrawBytes, sizeof DrawBytes)) return 0;
    HMODULE sdl = GetModuleHandleA("SDL2.dll"), image = GetModuleHandleA("SDL2_image.dll");
    if (!sdl || !image) return 0;
    CreateSurface = (CreateSurfaceFn)GetProcAddress(sdl, "SDL_CreateRGBSurface");
    FreeSurface = (FreeSurfaceFn)GetProcAddress(sdl, "SDL_FreeSurface");
    ReadPicture = (LoadImageFn)GetProcAddress(image, "IMG_Load");
    if (!CreateSurface || !FreeSurface || !ReadPicture) return 0;
    wchar_t wide[MAX_PATH];
    DWORD n = GetModuleFileNameW(ThisModule, wide, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    while (n && wide[n - 1] != L'\\') --n;
    wide[n] = 0;
    int bytes = WideCharToMultiByte(CP_UTF8, 0, wide, -1, MaskFolder, (int)sizeof(MaskFolder) - 16, 0, 0);
    if (bytes <= 0) return 0;
    const char *sub = "Skin Masks\\";
    for (unsigned i = 0; (MaskFolder[bytes - 1 + i] = sub[i]) != 0; ++i) {}
    DWORD old = 0;
    if (!VirtualProtect(Trampolines, sizeof Trampolines, PAGE_EXECUTE_READWRITE, &old)) return 0;
    BlitOriginal = Trampolines;
    DrawOriginal = Trampolines + Trampoline(Trampolines, BlitSite, sizeof BlitBytes);
    Trampoline((unsigned char *)DrawOriginal, DrawVillagerSite, sizeof DrawBytes);
    FlushInstructionCache(GetCurrentProcess(), Trampolines, sizeof Trampolines);
    if (!Jump(BlitSite, (void *)BlitHook, sizeof BlitBytes)) return 0;
    if (!Jump(DrawVillagerSite, (void *)DrawVillagerHook, sizeof DrawBytes)) {
        DWORD back = 0, ignored = 0;                          // all or nothing: the first hook comes out again
        if (VirtualProtect((void *)BlitSite, sizeof BlitBytes, PAGE_EXECUTE_READWRITE, &back)) {
            Copy((void *)BlitSite, BlitBytes, sizeof BlitBytes);
            VirtualProtect((void *)BlitSite, sizeof BlitBytes, back, &ignored);
        }
        return 0;
    }
    VF1Skin_Status.installed = 1;
    return 1;
}

// PROTOTYPE: a slot's tone, 0 (the game's own skin) or 1..10. The design keeps tones in a file per save.
extern "C" __declspec(dllexport) int __cdecl VF1Skin_SetTone(int slot, int tone) {
    if (slot < 0 || slot >= VILLAGER_SLOTS || tone < 0 || tone > SKIN_TONE_COUNT) return 0;
    Tones[slot] = (unsigned char)tone;
    return 1;
}

// For the tests: where the game's own blit continues (the emulator records every blit there).
extern "C" __declspec(dllexport) void *__cdecl VF1Skin_TestBlitOriginal() { return BlitOriginal; }
extern "C" __declspec(dllexport) void __cdecl VF1Skin_TestSetModule(unsigned module) { ThisModule = (HMODULE)module; }

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        ThisModule = module;
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}
