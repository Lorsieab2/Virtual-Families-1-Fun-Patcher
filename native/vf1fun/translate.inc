// translate.inc -- the patches' own text in the player's chosen translation (the Translations setting).
//
// Every line a player can see in this DLL is marked, and tools/vf1_patch_text.py lists the marked lines in
// data/vf1_patch_strings.json, from which the patcher's "Make a translation" template takes them (key
// "patch/vf1fun.<words>~<hash of the English>"). tests/test_patch_text_coverage.py fails on a line that is not marked.
//
//   TR(L"...")            translated now: the translation, or the English when there is none
//   TR_N(L"...")          only marked; translated where it is shown: Template::Begin / Item, Message, Confirm, and
//                         the static tables that go through Tr() where they are used. (A static initializer runs
//                         when this DLL loads, before vf1tr.dll, so it can only be marked.)
//   TR_A(room, "...")     a narrow line the game draws itself, translated now, at most `room` bytes
//   TR_NA(room, "...")    the same, only marked (a static table, translated with TrA where it is used)
//
// vf1tr.dll (loaded last, only with the Translations setting) finds a translation by its English and checks its
// room; without vf1tr.dll, or before it is loaded, every line is its English. Nothing here changes any text when no
// translation is chosen.

#define TR_N(s) s
#define TR_NA(room, s) s

typedef const wchar_t *(__cdecl *TrTextWFn)(const wchar_t *);
typedef const char *(__cdecl *TrTextAFn)(const char *, int);
typedef const char *(__cdecl *TrEnglishFn)(int);

static FARPROC TrFunction(const char *name) {
    HMODULE tr = GetModuleHandleW(L"vf1tr.dll");
    return tr ? GetProcAddress(tr, name) : 0;
}

static const wchar_t *Tr(const wchar_t *english) {
    static TrTextWFn fn;
    if (!fn) fn = (TrTextWFn)TrFunction("VF1Tr_TextW");
    return fn && english ? fn(english) : english;
}

static const char *TrA(const char *english, int room) {
    static TrTextAFn fn;
    if (!fn) fn = (TrTextAFn)TrFunction("VF1Tr_TextA");
    return fn && english ? fn(english, room) : english;
}

// A game line's English whatever the translation (a list the code searches by its English words).
static const char *GameEnglish(int id) {
    static TrEnglishFn fn;
    if (!fn) fn = (TrEnglishFn)TrFunction("VF1Tr_English");
    return fn ? fn(id) : 0;
}

#define TR(s) Tr(s)
#define TR_A(room, s) TrA(s, room)
