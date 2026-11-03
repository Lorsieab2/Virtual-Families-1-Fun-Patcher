// clipboard.inc -- included by vf1fun.cpp after text_names.inc.
//
// SETTING CopyPasteInTextBoxes (on by default): COPY AND PASTE IN THE GAME'S OWN TEXT BOXES.
//
// How keys reach a text box (VERIFIED in the exe). ldwGame's event loop (0x4047B0) turns SDL_KEYDOWN into messages:
// at 0x404826 it reads the key's code (event + 0x14, [esp+0x38]) and its modifiers (event + 0x18, [esp+0x3C]) and
// switches on the code (0x404840 / 0x404893): Backspace becomes (5, key, 8), Enter and Tab (6, 0x3EA / 0x3EB), Insert
// (6, 0x3F4), and V, C and X nothing at all. Typed letters come only from SDL_TEXTINPUT (0x4049A5), which SDL 2.0.3
// does not make while Ctrl is held (ToUnicode gives a control character, 0x16 for Ctrl+V, and SDL_SendKeyboardText
// drops anything below a space). Every message goes through the message manager (0x402140 -> 0x401DA0), which walks
// its listeners in order -- node {listener, flags, stop, next} -- calling listener->vtable[2](message, a, b) until one
// returns true. A text box's ldwTextControlImpl (vtable 0x4B2950, HandleMessage 0x40DA70) takes typing while +0x25
// (being edited) is set and its owner (+0x1C) is shown (+8): that is the box with the typing focus.
//
// The patch: a jump at 0x404826 (its 10 stock bytes checked first). For Ctrl+V or Shift+Insert, Ctrl+C or
// Ctrl+Insert, and Ctrl+X (no Alt, so AltGr letters are untouched) it looks for that box in the listeners. With one,
// the key is used here and never goes on to the game (so Insert's own message is not sent); with none, the key goes
// on exactly as in the stock game.
//   * Paste: the clipboard's CF_UNICODETEXT is added at the end of the box's text (a game box's caret is always at
//     the end). CR LF becomes ONE space, and a lone CR, LF or Tab one space each; other control characters and unpaired
//     surrogates are dropped; the text is composed (NFC, FoldStringW MAP_PRECOMPOSED) first, whichever setting is on;
//     a numbers-only box keeps only digits (and a '-' first, as the stock box allows). With Render Unicode with
//     In-Game Fonts or Use Unicode Font installed it is stored by the write rule (text_rule.inc) cut to the box's limit
//     at whole characters (grapheme clusters): a name box 1,200 bytes, any other box its own bytes. With neither, only
//     the characters the stock fonts can draw are kept, one byte each (U+0020..U+007E and U+00A2..U+00FF), cut to the
//     box's own byte limit.
//   * A held key: its auto-repeats (SDL's repeat flag) are swallowed while a box has the typing focus, so one press
//     acts once. Nothing is ever written
//     past the box's buffer (limit + 1 bytes, 0x40D370). The game is told the text changed (0xC, 0x401EA0), as
//     after a typed letter.
//   * Copy: the box's whole text (a name box holds the whole name, never its short form) as Unicode, read by the
//     one rule (UTF-8, else Windows-1252).
//   * Cut: copy, then the box is emptied -- only if the copy succeeded.
// vf1fun.dll's own Win32 windows are standard edit boxes, which already copy and paste themselves.

static const unsigned kKeyDownSite = 0x404826, kKeyDownOn = 0x404830, kKeyDownDone = 0x404A87;
static const unsigned kTextControlVtable = 0x4B2950;
static bool gClipboardOn;

typedef void *(__cdecl *ClipMessagesFn)();
typedef void (__thiscall *ClipChangedFn)(void *messages, int message, int a);
static const ClipMessagesFn ClipMessages = (ClipMessagesFn)0x402140;
static const ClipChangedFn ClipChanged = (ClipChangedFn)0x401EA0;

enum { CLIP_NONE = 0, CLIP_PASTE = 1, CLIP_COPY = 2, CLIP_CUT = 3 };

// For the tests (tests/test_clipboard.py): the clipboard is read and written through these, which the emulator
// replaces; in the game they are the real clipboard.
static int ClipAction(unsigned key, unsigned mod) {
    bool ctrl = (mod & 0x00C0) != 0, shift = (mod & 0x0003) != 0, alt = (mod & 0x0300) != 0;
    if (alt) return CLIP_NONE;
    if (ctrl && !shift && (key == 'v' || key == 'V')) return CLIP_PASTE;
    if (ctrl && !shift && (key == 'c' || key == 'C')) return CLIP_COPY;
    if (ctrl && !shift && (key == 'x' || key == 'X')) return CLIP_CUT;
    if (key == 0x40000049) {                              // SDLK_INSERT
        if (shift && !ctrl) return CLIP_PASTE;
        if (ctrl && !shift) return CLIP_COPY;
    }
    return CLIP_NONE;
}

// The text box with the typing focus: the first listener that is an ldwTextControlImpl being edited and shown.
static unsigned char *FocusedBox() {
    void **messages = (void **)ClipMessages();
    if (!messages || !*messages) return 0;
    unsigned char *node = *(unsigned char **)*messages;
    for (int guard = 0; node && guard < 100000; ++guard) {
        unsigned char *who = *(unsigned char **)node;
        unsigned flags = *(unsigned *)(node + 4);
        if (who && (flags & 2) && *(unsigned *)who == kTextControlVtable && who[0x25]) {
            unsigned char *owner = *(unsigned char **)(who + 0x1C);
            if (owner && owner[8] && *(char **)(who + 0x30)) return who;
        }
        node = *(unsigned char **)(node + 0xC);
    }
    return 0;
}

// vf1text.dll or vf1font.dll has its hooks installed (asked of the DLL, not guessed from its being loaded).
static bool UnicodeTextOn() { return TextActive != 0 && TextActive() != 0; }

static HWND ClipOwner() {
    HWND w = GetActiveWindow();
    if (w) return w;
    static HWND quiet;
    if (!quiet) quiet = CreateWindowExW(0, L"STATIC", L"", 0, 0, 0, 0, 0, HWND_MESSAGE, 0, 0, 0);
    return quiet;
}

// Fixed buffers only (no allocation): the clipboard's first ClipMax units are more than any box can hold.
static const int ClipMax = 8192;
static wchar_t ClipText[ClipMax + 1];

static wchar_t *ReadClipboardText() {
    if (!IsClipboardFormatAvailable(CF_UNICODETEXT) || !OpenClipboard(ClipOwner())) return 0;
    wchar_t *copy = 0;
    HANDLE h = GetClipboardData(CF_UNICODETEXT);
    const wchar_t *p = h ? (const wchar_t *)GlobalLock(h) : 0;
    if (p) {
        SIZE_T cap = GlobalSize(h) / sizeof(wchar_t);
        SIZE_T n = 0;
        while (n < cap && n < (SIZE_T)ClipMax && p[n]) ++n;
        memcpy(ClipText, p, n * sizeof(wchar_t));
        ClipText[n] = 0;
        copy = ClipText;
        GlobalUnlock(h);
    }
    CloseClipboard();
    return copy;
}

static bool WriteClipboardText(const wchar_t *text) {
    size_t n = wcslen(text);
    HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, (n + 1) * sizeof(wchar_t));
    if (!h) return false;
    wchar_t *p = (wchar_t *)GlobalLock(h);
    if (!p) { GlobalFree(h); return false; }
    memcpy(p, text, (n + 1) * sizeof(wchar_t));
    GlobalUnlock(h);
    if (!OpenClipboard(ClipOwner())) { GlobalFree(h); return false; }
    EmptyClipboard();
    bool ok = SetClipboardData(CF_UNICODETEXT, h) != 0;
    CloseClipboard();
    if (!ok) GlobalFree(h);
    return ok;
}

typedef wchar_t *(__cdecl *ClipReadFn)();
typedef bool (__cdecl *ClipWriteFn)(const wchar_t *);
extern "C" __declspec(dllexport) ClipReadFn VF1Fun_ClipRead = &ReadClipboardText;
extern "C" __declspec(dllexport) ClipWriteFn VF1Fun_ClipWrite = &WriteClipboardText;
extern "C" __declspec(dllexport) volatile unsigned VF1Fun_ClipboardInstalled = 0;

// A text with its accents composed (FoldStringW MAP_PRECOMPOSED: "e" + U+0308 -> "ë"); else as it is.
static wchar_t ClipNfc[ClipMax * 3 + 1];
static const wchar_t *Composed(const wchar_t *s) {
    int n = (int)wcslen(s);
    if (n > ClipMax) n = ClipMax;
    wchar_t *out = ClipNfc;
    int got = n ? FoldStringW(MAP_PRECOMPOSED, s, n, out, ClipMax * 3) : 0;
    if (got <= 0) { memcpy(out, s, (size_t)n * sizeof(wchar_t)); got = n; }
    out[got] = 0;
    return out;
}

// The box's text as Unicode by the one rule (per sequence); a short form as its whole name (a name box
// opens with the whole name, so this is only ever a box filled some other way).
static const wchar_t *BoxTextW(const char *buf) {
    int n = 0;
    while (n < VF1_NAME_BOX_BYTES && buf[n]) ++n;
    return NameW(buf, n);
}

// Paste `clip` into the box: the rules above. Returns the bytes added.
static int PasteInto(unsigned char *box, const wchar_t *clip) {
    char *buf = *(char **)(box + 0x30);
    int limit = *(int *)(box + 0x28);
    bool numeric = box[0x2D] != 0;
    if (box[0x2F] || limit <= 0 || limit > VF1_NAME_BOX_BYTES) return 0;   // a box in its other mode: as typing
    int len = 0;
    while (len < limit && buf[len]) ++len;
    // CR, LF and Tab -> a space; numbers-only boxes keep digits (and a first '-')
    static wchar_t clean[ClipMax + 1];
    size_t cn = wcslen(clip);
    if (cn > (size_t)ClipMax) cn = ClipMax;
    size_t k = 0;
    for (size_t i = 0; i < cn; ++i) {
        wchar_t c = clip[i];
        if (c == L'\r' && i + 1 < cn && clip[i + 1] == L'\n') continue;       // CR LF is one space: the LF makes it
        if (c == L'\r' || c == L'\n' || c == L'\t') c = L' ';
        if (numeric && !(c >= L'0' && c <= L'9') && !(c == L'-' && len == 0 && k == 0)) continue;
        clean[k++] = c;
    }
    clean[k] = 0;
    // composed (NFC) whichever Unicode setting is on, or neither: "e" + U+0308 pastes as e with a diaeresis
    const wchar_t *composed = Composed(clean);
    k = wcslen(composed);
    int added = 0;
    if (UnicodeTextOn()) {
        // the box's text and the pasted text as one name, cut at whole characters to the box's room
        // (the box's own text as one rule reads it: never a short form's whole name here)
        static wchar_t had[VF1_NAME_BOX_BYTES + 8], all[VF1_NAME_BOX_BYTES + ClipMax + 2];
        static wchar_t keptText[VF1_NAME_BOX_BYTES + 8], newText[VF1_NAME_BOX_BYTES + 8];
        static char out[VF1_NAME_BOX_BYTES + 8], before[VF1_NAME_BOX_BYTES + 8];
        size_t hl = (size_t)DecodeStoredW(buf, len, had, VF1_NAME_BOX_BYTES + 6);   // the box's text, per sequence
        int old = FitNameStored(had, before, limit);          // the box's text alone, stored by the write rule
        memcpy(all, had, hl * sizeof(wchar_t));
        memcpy(all + hl, composed, (k + 1) * sizeof(wchar_t));
        int got = FitNameStored(all, out, limit);             // control characters and lone surrogates are dropped
        // never lose what was there (a pasted mark joining the last letter that then no longer fits): the new text
        // must start with the box's text, and be longer
        size_t kl = (size_t)DecodeStoredW(before, old, keptText, VF1_NAME_BOX_BYTES + 6);
        size_t nl = (size_t)DecodeStoredW(out, got, newText, VF1_NAME_BOX_BYTES + 6);
        bool keepsOld = nl >= kl && memcmp(newText, keptText, kl * sizeof(wchar_t)) == 0;
        if (keepsOld && nl > kl) {
            memcpy(buf, out, (size_t)got);                    // got <= limit: the buffer has limit + 1 bytes
            buf[got] = 0;
            added = got > old ? got - old : 1;
        }
    } else {
        const wchar_t *src = composed;
        int at = len;
        for (size_t i = 0; src[i] && at < limit; ++i) {
            wchar_t c = src[i];
            if ((c >= 0x20 && c <= 0x7E) || (c >= 0xA2 && c <= 0xFF)) buf[at++] = (char)c;   // the stock fonts' letters
        }
        buf[at] = 0;
        added = at - len;
    }
    return added;
}

// The key handler: true when the key was used by a focused box.
static int __cdecl ClipKeyDown(unsigned key, unsigned mod, unsigned repeat) {
    int action = ClipAction(key, mod & 0xFFFF);
    if (action == CLIP_NONE) return 0;
    unsigned char *box = FocusedBox();
    if (!box) return 0;
    if (repeat) return 1;                                    // a held key's auto-repeat: the first press acted, this one is used and does nothing
    char *buf = *(char **)(box + 0x30);
    if (action == CLIP_PASTE) {
        wchar_t *clip = VF1Fun_ClipRead();
        if (clip && PasteInto(box, clip)) ClipChanged(ClipMessages(), 0xC, *(int *)(box + 4));
        return 1;
    }
    if (box[0x2F]) return 1;                                 // a box in its other mode: nothing to copy
    if (buf[0]) {
        bool copied = VF1Fun_ClipWrite(BoxTextW(buf));
        if (action == CLIP_CUT && copied) {
            buf[0] = 0;
            ClipChanged(ClipMessages(), 0xC, *(int *)(box + 4));
        }
    }
    return 1;
}

__declspec(naked) static void ClipKeyDownDetour() {
    __asm {
        movzx eax, byte ptr [esp + 0x31]     // SDL_KeyboardEvent.repeat: 1 for a held key's auto-repeat
        push eax
        movzx edx, word ptr [esp + 0x40]     // the key's modifiers ([esp+0x3C] before the push)
        push edx
        push dword ptr [esp + 0x40]          // the key's code ([esp+0x38] before the two pushes)
        call ClipKeyDown
        add esp, 12
        test eax, eax
        jnz used
        mov ecx, dword ptr [esp + 0x38]      // the stock instructions, then on
        cmp ecx, 0x4000003A
        push kKeyDownOn
        ret
    used:
        push kKeyDownDone
        ret
    }
}

static void InstallClipboard() {
    static const unsigned char stock[] = {
        0x8B, 0x4C, 0x24, 0x38,                 // mov ecx, [esp+0x38]
        0x81, 0xF9, 0x3A, 0x00, 0x00, 0x40 };   // cmp ecx, 0x4000003A
    if (!BytesAre(kKeyDownSite, stock, sizeof stock)) return;   // not the stock game: the keys stay as they are
    gClipboardOn = InstallJump(kKeyDownSite, stock, sizeof stock, (void *)&ClipKeyDownDetour);
    if (gClipboardOn) VF1Fun_ClipboardInstalled = 1;
}
