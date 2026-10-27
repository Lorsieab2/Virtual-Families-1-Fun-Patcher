// outfits.inc -- included by vf1fun.cpp after features.inc.
//
// FIX (Fix Vanilla Game Bugs): EVERY OUTFIT OF A KIND IN THE TRAY IS THE LAST ONE BOUGHT.
//
// The store draws one clothes picture (0..49) for the Male Outfit and one for
// the Female Outfit (inventory 0x8957A0 +0x108 / +0x10C, 0x496C70). Buying one
// (0x4969A0, items 18 / 19) copies it to ONE field per kind, +0x110 / +0x114,
// and the tray gets an item 64 / 65 (0x449B58: TrayAddItem 0x4973E0). The tray
// (0x8958E8) keeps only (item, uses) per place, eight places of 8 bytes, so
// every outfit of a kind in it reads that one field:
//   - the tray draws each place with 0x496A10 (0x496F80, call at 0x496FCD), and
//     the outfit being dragged (0x496FE0, call at 0x49703C); 0x496A10 draws
//     item 64 / 65 at the picture +0x110 / +0x114 (0x496A72 / 0x496A83);
//   - dropping it on a family member (the drop handler, 0x446EB9) sets the
//     body (villager +0x2A64) to 0x496D10(64 / 65), which is +0x110 / +0x114
//     (call at 0x446EEF).
// So buying a second Male Outfit changes the picture of the first one in the
// tray AND what the first one puts on: both give the last one bought.
//
// What it should be: each bought outfit keeps the picture it had when it was
// bought, and putting it on gives that outfit. The tray place has no spare
// field (its second dword is the uses left, which 0x497480 counts down and the
// tray removes the item at 0), and the save has none either, so the picture of
// each place is kept here, in memory, and per save in a sidecar .dat beside the
// save file:
//   "<save folder>\Virtual Families 1 Patcher Data\Outfits\<save file>.dat"
// Nothing is added to or changed in the game's records or its save. A place
// with no known picture (an outfit bought before the fix, or a save the
// sidecar does not describe) gives exactly what the stock game gives.
//
// The hooks (every one checked against the stock bytes first, all or none):
//   0x449B58 the buy's TrayAddItem: the place it fills gets the picture just bought
//   0x4976D6 / 0x4977D4 the tray's swap 0x497520: the pictures move with the outfits
//   0x496FCD / 0x49703C the tray's two draws: the place's own picture for the draw
//   0x446EEF the drop handler's 0x496D10: the place's own picture is put on
// The draws lend the place's picture to +0x110 / +0x114 for that one call and
// put the field back at once, so the field the save holds is never changed.

static const unsigned kOutfitPlaces = 8;            // the tray's places (0x497330 searches 8)
static const int kMaleOutfit = 64, kFemaleOutfit = 65;
static const int kOutfitPictures = 50;              // 0x496C70 draws rand(50)
struct OutfitPlace { int item; int uses; int picture; };  // picture -1: not known (the stock game's)
static OutfitPlace gOutfits[kOutfitPlaces];
static bool gOutfitFixOn;
static bool gOutfitShut[6];                          // a slot's sidecar was there but could not be read

static int *TrayPlace(unsigned place) { return (int *)((unsigned char *)ToolTray + place * 8); }
static int TrayDragged() { return *(int *)((unsigned char *)ToolTray + 0xA0); }
static int *OutfitField(int item) {
    return (int *)((unsigned char *)Inventory + (item == kMaleOutfit ? 0x110 : 0x114));
}

static void ForgetOutfits() {
    for (unsigned k = 0; k < kOutfitPlaces; ++k) { gOutfits[k].item = 0; gOutfits[k].uses = 0; gOutfits[k].picture = -1; }
}

// The place's own picture, or -1 when it is not known or the place no longer holds that outfit.
static int OutfitPicture(int place, int item) {
    if (place < 0 || place >= (int)kOutfitPlaces || (item != kMaleOutfit && item != kFemaleOutfit))
        return -1;
    const OutfitPlace &o = gOutfits[place];
    if (o.item != item || TrayPlace(place)[0] != item || o.picture < 0 || o.picture >= kOutfitPictures)
        return -1;
    return o.picture;
}

// ---------------------------------------------------------------- the hooks
typedef int (__thiscall *TrayFirstFreeFn)(void *tray);
typedef void (__thiscall *TraySwapFn)(void *tray, int a, int b);
typedef int (__thiscall *TraySlotAtFn)(void *tray, int x, int y);
typedef void (__thiscall *DrawItemFn)(void *inventory, int x, int y, int item, int a, int b, int c);
typedef int (__thiscall *OutfitBodyFn)(void *inventory, int item);
static const TrayFirstFreeFn TrayFirstFree = (TrayFirstFreeFn)0x497330;
static const TraySwapFn TraySwap = (TraySwapFn)0x497520;
static const TraySlotAtFn TraySlotAt = (TraySlotAtFn)0x497310;
static const DrawItemFn DrawItem = (DrawItemFn)0x496A10;
static const OutfitBodyFn OutfitBody = (OutfitBodyFn)0x496D10;

// The store's buy (0x449B58): TrayAddItem(item, uses) fills the first free place (0x497330), and the
// bought picture is already in +0x110 / +0x114 (0x4969A0 ran at 0x449B05).
static bool __fastcall BuyIntoTray(void *tray, void *, int item, int uses) {
    int place = TrayFirstFree(tray);
    bool ok = TrayAddItem(tray, item, uses);
    if (ok && place >= 0 && place < (int)kOutfitPlaces) {
        OutfitPlace &o = gOutfits[place];
        o.item = item;
        o.uses = uses;
        o.picture = (item == kMaleOutfit || item == kFemaleOutfit) ? *OutfitField(item) : -1;
    }
    return ok;
}

// The tray's swap (0x497520(a, b): a == b or a place of -1 swaps nothing).
static void __fastcall SwapInTray(void *tray, void *, int a, int b) {
    if (a >= 0 && b >= 0 && a < (int)kOutfitPlaces && b < (int)kOutfitPlaces && a != b) {
        OutfitPlace t = gOutfits[a];
        gOutfits[a] = gOutfits[b];
        gOutfits[b] = t;
    }
    TraySwap(tray, a, b);
}

static void DrawPlace(void *inventory, int place, int x, int y, int item, int a, int b, int c) {
    int picture = OutfitPicture(place, item);
    if (picture < 0) { DrawItem(inventory, x, y, item, a, b, c); return; }
    int *field = OutfitField(item);
    int kept = *field;
    *field = picture;                    // lent for this one draw
    DrawItem(inventory, x, y, item, a, b, c);
    *field = kept;
}

// The tray's places (0x496F80 draws place k at y = top + k * height + height / 2; 0x497310 maps it back).
static void __fastcall DrawTrayPlace(void *inventory, void *, int x, int y, int item, int a, int b, int c) {
    DrawPlace(inventory, TraySlotAt(ToolTray, x, y), x, y, item, a, b, c);
}

// The outfit being dragged (0x496FE0 draws the place at tray +0xA0).
static void __fastcall DrawDragged(void *inventory, void *, int x, int y, int item, int a, int b, int c) {
    DrawPlace(inventory, TrayDragged(), x, y, item, a, b, c);
}

// Dropping an outfit on a family member: the body it puts on (the place is the dragged one, tray +0xA0,
// which 0x497480 uses up right after).
static int __fastcall PutOnOutfit(void *inventory, void *, int item) {
    int picture = OutfitPicture(TrayDragged(), item);
    return picture >= 0 ? picture : OutfitBody(inventory, item);
}

static bool CallIs(unsigned site, unsigned target) {
    unsigned char call[5] = { 0xE8 };
    *(int *)(call + 1) = (int)(target - (site + 5));
    return BytesAre(site, call, 5);
}

static void RetargetCall(unsigned site, void *replacement) {
    int rel = (int)((unsigned)replacement - (site + 5));
    WriteCode(site + 1, &rel, 4);
}

static void InstallOutfitPictureFix() {
    // The stock code the fix depends on, besides the six calls.
    static const unsigned char buy[] = {           // 0x4969A0 items 18 / 19: +0x108 -> +0x110, +0x10C -> +0x114
        0x83, 0xFA, 0x12, 0x75, 0x0F, 0x8B, 0x91, 0x08, 0x01, 0x00, 0x00, 0x89, 0x91, 0x10, 0x01, 0x00, 0x00,
        0xC2, 0x04, 0x00, 0x83, 0xFA, 0x13, 0x75, 0x0C, 0x8B, 0x81, 0x0C, 0x01, 0x00, 0x00, 0x89, 0x81, 0x14,
        0x01, 0x00, 0x00 };
    static const unsigned char body[] = {          // 0x496D10: 64 -> +0x110, 65 -> +0x114, else 0
        0x8B, 0x44, 0x24, 0x04, 0x83, 0xF8, 0x40, 0x75, 0x09, 0x8B, 0x81, 0x10, 0x01, 0x00, 0x00, 0xC2, 0x04,
        0x00, 0x83, 0xF8, 0x41, 0x75, 0x09, 0x8B, 0x81, 0x14, 0x01, 0x00, 0x00, 0xC2, 0x04, 0x00 };
    static const unsigned char drawMale[] = { 0x8B, 0xBA, 0x10, 0x01, 0x00, 0x00 };    // 0x496A76 mov edi, [edx+0x110]
    static const unsigned char drawFemale[] = { 0x8B, 0xB9, 0x14, 0x01, 0x00, 0x00 };  // 0x496A87 mov edi, [ecx+0x114]
    static const unsigned char buyAdd[] = { 0x50, 0x56, 0xB9, 0xE8, 0x58, 0x89, 0x00 };  // 0x449B51 push eax; push esi; mov ecx, tray
    if (!BytesAre(0x4969BB, buy, sizeof buy) || !BytesAre(0x496D10, body, sizeof body)
        || !BytesAre(0x496A76, drawMale, sizeof drawMale) || !BytesAre(0x496A87, drawFemale, sizeof drawFemale)
        || !BytesAre(0x449B51, buyAdd, sizeof buyAdd)
        || !CallIs(0x449B58, 0x4973E0) || !CallIs(0x4976D6, 0x497520) || !CallIs(0x4977D4, 0x497520)
        || !CallIs(0x496FCD, 0x496A10) || !CallIs(0x49703C, 0x496A10) || !CallIs(0x446EEF, 0x496D10))
        return;  // not the stock game (or already installed): nothing is changed
    ForgetOutfits();
    RetargetCall(0x449B58, (void *)&BuyIntoTray);
    RetargetCall(0x4976D6, (void *)&SwapInTray);
    RetargetCall(0x4977D4, (void *)&SwapInTray);
    RetargetCall(0x496FCD, (void *)&DrawTrayPlace);
    RetargetCall(0x49703C, (void *)&DrawDragged);
    RetargetCall(0x446EEF, (void *)&PutOnOutfit);
    gOutfitFixOn = true;
}

// ---------------------------------------------------------------- the sidecar
// 148 bytes, little-endian: "VF1OUTFT", version 1, the game tag "VF1V101", the file's size (24 bytes);
// what it describes (84 bytes): the tray's eight places as saved (item, uses: tray +0 .. +0x3F) and the
// inventory's outfit fields as saved (+0x108 / +0x10C the store's pictures, +0x110 / +0x114 the last
// bought, +0x118 the next redraw); the eight places' pictures (-1 not known, else 0..49 for an outfit
// place); the FNV-1a 64 of everything before it. All of those game fields are in the save (CToolTray
// gs+0xDBCC, CInventoryManager gs+0xDA78), so the file is used only when the loaded save holds exactly
// the tray and outfit fields it was written with; any other save (an older or newer one, a different
// family, a game saved while the fix was off) gives the stock game's pictures. Python tools that edit a
// save (Rename Family, Game Speed) never touch those fields, so they keep the pictures.
static const unsigned kOutfitFileVersion = 1;
static const unsigned kOutfitBind = 24;                               // the described state
static const unsigned kOutfitPics = kOutfitBind + kOutfitPlaces * 8 + 5 * 4;
static const unsigned kOutfitFileSize = kOutfitPics + kOutfitPlaces * 4 + 8;
static const unsigned kOutfitInventoryFields[5] = { 0x108, 0x10C, 0x110, 0x114, 0x118 };

static unsigned long long OutfitFnv(const unsigned char *p, unsigned n) {
    unsigned long long h = 0xCBF29CE484222325ull;
    for (unsigned i = 0; i < n; ++i) { h ^= p[i]; h *= 0x100000001B3ull; }
    return h;
}
static void OutfitPut32(unsigned char *p, unsigned v) { memcpy(p, &v, 4); }
static unsigned OutfitGet32(const unsigned char *p) { unsigned v; memcpy(&v, p, 4); return v; }

// The game state the file describes, as it is now in memory (84 bytes).
static void OutfitBinding(unsigned char *out) {
    for (unsigned k = 0; k < kOutfitPlaces; ++k) {
        OutfitPut32(out + k * 8, (unsigned)TrayPlace(k)[0]);
        OutfitPut32(out + k * 8 + 4, (unsigned)TrayPlace(k)[1]);
    }
    for (unsigned f = 0; f < 5; ++f)
        OutfitPut32(out + kOutfitPlaces * 8 + f * 4, *(unsigned *)((unsigned char *)Inventory + kOutfitInventoryFields[f]));
}

// Builds the file from the tray as it is now and the places' known pictures.
static void EncodeOutfits(unsigned char *out) {
    memset(out, 0, kOutfitFileSize);
    memcpy(out, "VF1OUTFT", 8);
    OutfitPut32(out + 8, kOutfitFileVersion);
    memcpy(out + 12, "VF1V101\0", 8);
    OutfitPut32(out + 20, kOutfitFileSize);
    OutfitBinding(out + kOutfitBind);
    for (unsigned k = 0; k < kOutfitPlaces; ++k)
        OutfitPut32(out + kOutfitPics + k * 4, (unsigned)OutfitPicture((int)k, gOutfits[k].item));
    unsigned long long sum = OutfitFnv(out, kOutfitFileSize - 8);
    OutfitPut32(out + kOutfitFileSize - 8, (unsigned)sum);
    OutfitPut32(out + kOutfitFileSize - 4, (unsigned)(sum >> 32));
}

// 1: valid and it describes the game now, its pictures are known again; 0: valid, but for another state
// of the save or another save (nothing is taken from it); -1: damaged (not this file format).
static int DecodeOutfits(const unsigned char *in, unsigned n) {
    if (n != kOutfitFileSize || memcmp(in, "VF1OUTFT", 8) != 0 || memcmp(in + 12, "VF1V101\0", 8) != 0
        || OutfitGet32(in + 8) != kOutfitFileVersion || OutfitGet32(in + 20) != kOutfitFileSize)
        return -1;
    unsigned long long sum = OutfitFnv(in, n - 8);
    if (OutfitGet32(in + n - 8) != (unsigned)sum || OutfitGet32(in + n - 4) != (unsigned)(sum >> 32))
        return -1;
    for (unsigned k = 0; k < kOutfitPlaces; ++k) {
        int item = (int)OutfitGet32(in + kOutfitBind + k * 8), picture = (int)OutfitGet32(in + kOutfitPics + k * 4);
        bool outfit = item == kMaleOutfit || item == kFemaleOutfit;
        if (picture != -1 && (!outfit || picture < 0 || picture >= kOutfitPictures))
            return -1;
    }
    unsigned char now[kOutfitPics - kOutfitBind];
    OutfitBinding(now);
    if (memcmp(now, in + kOutfitBind, sizeof now) != 0)
        return 0;
    for (unsigned k = 0; k < kOutfitPlaces; ++k) {
        int picture = (int)OutfitGet32(in + kOutfitPics + k * 4);
        gOutfits[k].item = TrayPlace(k)[0];
        gOutfits[k].uses = TrayPlace(k)[1];
        gOutfits[k].picture = picture;
    }
    return 1;
}

static HANDLE OutfitOpen(const char *path, DWORD *error) {
    for (unsigned k = 0;; ++k) {
        HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
        if (h != INVALID_HANDLE_VALUE) { *error = 0; return h; }
        DWORD e = GetLastError();
        bool transient = e == ERROR_SHARING_VIOLATION || e == ERROR_LOCK_VIOLATION || e == ERROR_ACCESS_DENIED;
        if (!transient || k + 1 >= 5) { *error = e; return h; }
        Sleep(250);
    }
}

typedef const char *(__thiscall *SavePathFn)(void *state, int slot);  // theGameState vtable +0xC (MakePath)
static const unsigned kOutfitPathCap = MAX_PATH + 160;
// The slot's sidecar, beside its save file: "<save folder>\Virtual Families 1 Patcher Data\Outfits\<save>.dat".
static bool OutfitPaths(void *state, int slot, char *folder, char *sidecar) {
    const char *s = ((SavePathFn)(*(void ***)state)[3])(state, slot);
    if (!s) return false;
    size_t n = strlen(s), cut = n;
    if (n == 0 || n + 1 >= MAX_PATH) return false;
    while (cut > 0 && s[cut - 1] != '\\' && s[cut - 1] != '/') --cut;
    if (cut == 0 || cut == n) return false;
    static const char middle[] = "Virtual Families 1 Patcher Data\\Outfits";
    memcpy(folder, s, cut);
    memcpy(folder + cut, middle, sizeof middle);
    return snprintf(sidecar, kOutfitPathCap, "%s\\%s.dat", folder, s + cut) < (int)kOutfitPathCap;
}

// True when the damaged file is now beside itself ("<name>.unreadable-N.dat"); it is never deleted.
static bool OutfitMoveAside(const char *path) {
    char aside[kOutfitPathCap + 32];
    size_t n = strlen(path);
    if (n < 4 || n + 20 > sizeof aside) return false;
    for (unsigned k = 1; k < 1000; ++k) {
        snprintf(aside, sizeof aside, "%.*s.unreadable-%u.dat", (int)(n - 4), path, k);
        if (MoveFileExA(path, aside, 0)) return true;
        DWORD e = GetLastError();
        if (e != ERROR_ALREADY_EXISTS && e != ERROR_FILE_EXISTS) return false;
    }
    return false;
}

// After theGameState::Load(slot) succeeded: the tray is the save's; its pictures come from the sidecar.
static void OutfitsAfterLoad(void *state, int slot) {
    if (!gOutfitFixOn || slot < 1 || slot > 5) return;
    ForgetOutfits();
    gOutfitShut[slot] = false;
    char folder[MAX_PATH + 64], path[kOutfitPathCap];
    if (!OutfitPaths(state, slot, folder, path)) return;
    DWORD error = 0;
    HANDLE h = OutfitOpen(path, &error);
    if (h == INVALID_HANDLE_VALUE) {
        if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND)
            gOutfitShut[slot] = true;  // there but could not be opened: never replaced unread
        return;                        // missing (an old save): none known, the stock game's pictures
    }
    unsigned char file[kOutfitFileSize + 1];
    DWORD got = 0;
    BOOL ok = ReadFile(h, file, sizeof file, &got, 0);
    CloseHandle(h);
    if (!ok) { gOutfitShut[slot] = true; return; }
    if (DecodeOutfits(file, got) < 0 && !OutfitMoveAside(path))
        gOutfitShut[slot] = true;  // a damaged file that could not be moved is kept, and not replaced
}

// After theGameState::Save(slot) succeeded: the sidecar describes the tray just saved.
static void OutfitsAfterSave(void *state, int slot) {
    if (!gOutfitFixOn || slot < 1 || slot > 5 || gOutfitShut[slot]) return;
    char folder[MAX_PATH + 64], path[kOutfitPathCap], temp[kOutfitPathCap + 8];
    if (!OutfitPaths(state, slot, folder, path)) return;
    bool any = false;
    for (unsigned k = 0; k < kOutfitPlaces; ++k)
        if (OutfitPicture((int)k, gOutfits[k].item) >= 0) any = true;
    if (!any && GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES)
        return;  // nothing to remember and no file to keep up to date
    unsigned char file[kOutfitFileSize];
    EncodeOutfits(file);
    char parent[MAX_PATH + 64];
    snprintf(parent, sizeof parent, "%s", folder);
    char *cut = strrchr(parent, '\\');
    if (cut) { *cut = 0; CreateDirectoryA(parent, 0); }
    CreateDirectoryA(folder, 0);
    snprintf(temp, sizeof temp, "%s.tmp", path);
    HANDLE h = CreateFileA(temp, GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    BOOL ok = WriteFile(h, file, kOutfitFileSize, &written, 0) && written == kOutfitFileSize;
    if (ok) ok = FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok || !MoveFileExA(temp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        DeleteFileA(temp);
}

// theGameState::Init (a new family): the tray is reset (0x497580), so nothing is known.
static void OutfitsReset() {
    ForgetOutfits();
}
