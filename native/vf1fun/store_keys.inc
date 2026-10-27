// store_keys.inc -- included by vf1fun.cpp after outfits.inc.
//
// CHEAT (setting StoreRefreshKey, on by default): R REFRESHES THE STORE'S FLEA MARKET AND ITS RANDOM CLOTHING.
//
// The stock store already has a hidden key. theStoreScene::HandleEvent (0x4499D0, the store scene's vtable
// slot 2) gets every typed character as (5, 0, character) (SDL_TEXTINPUT, posted at 0x4049C4), and:
//   0x4499EA  cmp eax, 0x72 ; jne 0x449A62        a small 'r' only
//   0x4499EF  mov ecx, 0x8957A0 ; call 0x496DB0   may it redraw? (the inventory's specials due time, +0x13C)
//   0x4499F9  test al, al ; je 0x449A62           no: nothing happens
//   0x4499FD  push -1 ; call 0x449480             the six random items (the owner's "Flea Market"; the code's
//                                                 "specials", store places 8..13)
//   0x449A06  push 1 ; call 0x496C70              the random Male Outfit and Female Outfit pictures (rand(50) each)
//   0x449A12  call 0x449100                       the store's labels
// 0x496DB0 refuses while the due time is 3 to 4 real hours away (so less than 1 real hour since the last draw);
// when it allows, it sets the due time to now + 4 real hours (0x3840) and returns 1.
//
// The cheat makes the same key work every time it is pressed, and with a capital R too: the jump at 0x4499EA
// goes to StoreRefreshKeyDetour, which takes 'r' (0x72) or 'R' (0x52), clears the due time and asks the game's
// own 0x496DB0, which then always allows and writes the due time exactly as the stock key does; then the
// stock code at 0x4499FD runs the game's own draws. Nothing else changes: the half-price grocery (+0x11C,
// 0x496CD0, its own 12-hour timer) is not drawn by this key, stock or patched; an outfit already bought keeps
// its picture (the bought fields +0x110 / +0x114 and the outfit fix's places are not written by 0x496C70).
// Any other character goes on to 0x449A62, as in the stock game (M, m and Esc are handled before 0x4499EA).
// It only ever runs inside the store scene's own key handler, so no other screen is affected (the house's
// K / k / R TV-remote keys are in theHouseScene, 0x440B40) and the Upgrades menu's pages (Win32 dialogs,
// including its Flea Market page, which lists everything at once and has nothing to redraw) never reach it.
//
// All or none: the 19 bytes at 0x4499EA and the whole of 0x496DB0 are checked against the stock game
// first; anything else (another version, another patch) leaves the stock key as it is.

static const unsigned kStoreKeySite = 0x4499EA;   // cmp eax, 0x72 .. je 0x449A62 (up to 0x4499FD)
static const unsigned kStoreRedrawAllowed = 0x496DB0;
static bool gStoreRefreshKeyOn;

__declspec(naked) static void StoreRefreshKeyDetour() {
    __asm {
        cmp eax, 0x72                       // 'r', the stock key
        je redraw
        cmp eax, 0x52                       // 'R'
        je redraw
        push 0x449A62                       // any other character: as the stock game
        ret
    redraw:
        mov dword ptr ds:[0x8958DC], 0      // inventory 0x8957A0 + 0x13C, the due time: long past
        mov ecx, 0x8957A0
        mov eax, 0x496DB0                   // the game's own check: now allows, and sets the due time
        call eax
        test al, al
        jz none
        push 0x4499FD                       // the stock redraw: specials, outfit pictures, labels
        ret
    none:
        push 0x449A62
        ret
    }
}

static void InstallStoreRefreshKey() {
    static const unsigned char key[] = {
        0x83, 0xF8, 0x72,                   // cmp eax, 0x72
        0x75, 0x73,                         // jne 0x449A62
        0xB9, 0xA0, 0x57, 0x89, 0x00,       // mov ecx, 0x8957A0
        0xE8, 0xB7, 0xD3, 0x04, 0x00,       // call 0x496DB0
        0x84, 0xC0,                         // test al, al
        0x74, 0x65 };                       // je 0x449A62
    static const unsigned char allowed[] = {  // 0x496DB0 .. 0x496DEB
        0x56, 0x8B, 0xF1, 0xE8, 0xA8, 0xC8, 0xF8, 0xFF, 0x8B, 0xC8, 0xE8, 0x11, 0xC9, 0xF6, 0xFF, 0x8B, 0x8E,
        0x3C, 0x01, 0x00, 0x00, 0x8D, 0x90, 0x30, 0x2A, 0x00, 0x00, 0x3B, 0xD1, 0x77, 0x0E, 0x8D, 0x90, 0x40,
        0x38, 0x00, 0x00, 0x3B, 0xD1, 0x72, 0x04, 0x32, 0xC0, 0x5E, 0xC3, 0x05, 0x40, 0x38, 0x00, 0x00, 0x89,
        0x86, 0x3C, 0x01, 0x00, 0x00, 0xB0, 0x01, 0x5E, 0xC3 };
    if (!BytesAre(kStoreRedrawAllowed, allowed, sizeof allowed) || !BytesAre(kStoreKeySite, key, sizeof key))
        return;  // not the stock game (or already installed): the stock key is left as it is
    gStoreRefreshKeyOn = InstallJump(kStoreKeySite, key, sizeof key, (void *)&StoreRefreshKeyDetour);
}
