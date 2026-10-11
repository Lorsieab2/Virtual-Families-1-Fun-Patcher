// songs.inc -- "VF1 + VF2 Songs": the Virtual Families 2 songs, played in
// addition to the Virtual Families 1 songs.
//
// The game's music manager (theGame's, constructed at 0x44C670 from the name
// table at 0x4F2818) holds five ldwSoundTrack wrappers: +0 the menu music,
// +4/+8/+0xC/+0x10 song1..song4, and +0x14 the track now playing. The Options
// screen's "Music Tracks" switches are four flag bytes (theGameState +0x1B16F..72)
// and the manager's "play next" (0x44C6F0, called from six places) walks the four
// song slots in order, skipping the switched-off ones.
//
// Each time "play next" is called, every slot is first pointed at either its VF1
// track or the matching VF2 track (a random one, except that the track now playing
// stays in its own slot so the stock walk still finds its place). The stock code
// then plays the next slot as it always did, so the order, the four switches and
// the volume behave as before, and each slot is a coin flip between the two games'
// songs. The menu music is chosen the same way. The VF2 files are
// "Virtual Families 1 Patcher Files\VF2 Songs\menu.ogg, song1.ogg ... song4.ogg",
// loaded by the game's own ldwSoundTrack constructor (0x40CC40). A file that does
// not load is simply never offered.

typedef void *(__thiscall *SoundTrackCtorFn)(void *wrapper, const char *file);
typedef void (__thiscall *PlayNextFn)(void *manager, bool menu);
static const SoundTrackCtorFn SoundTrackCtor = (SoundTrackCtorFn)0x40CC40;
static const PlayNextFn PlayNextStock = (PlayNextFn)0x44C6F0;
static const unsigned kPlayNextCallers[] = { 4416164, 4476562, 4486129, 4486159, 4491219, 4507839 };

#ifdef VF1FUN_TEST_LOG   // test builds only (native\build.bat never defines it): what loaded and what the rotation picked
static void TestLog(const char *text) {
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(Module, path, MAX_PATH);
    wchar_t *slash = wcsrchr(path, L'\\');
    if (slash) wcscpy_s(slash + 1, MAX_PATH - (slash + 1 - path), L"songs_test.log");
    FILE *f = 0;
    if (_wfopen_s(&f, path, L"a") == 0 && f) { fputs(text, f); fclose(f); }
}
#endif

static void *gVF2Track[5];      // 0 menu, 1..4 song1..song4 (0 = not loaded)
static void *gVF1Track[5];      // the stock tracks, remembered on the first call
static bool gSongsReady;

// An ldwSoundTrack wrapper points at its impl (+0); the impl keeps the loaded
// stream at +0xC (ogg/mp3/wav) or the sample at +8 (anything else) -- both zero
// when the file could not be opened (0x40CAE2 / 0x40CAF0).
static bool TrackLoaded(void *wrapper) {
    if (!wrapper) return false;
    unsigned char *impl = *(unsigned char **)wrapper;
    return impl && (*(void **)(impl + 0xC) || *(void **)(impl + 8));
}

static void *LoadVF2Track(const char *name) {
    wchar_t wide[MAX_PATH];
    GetModuleFileNameW(Module, wide, MAX_PATH);       // ...\Virtual Families 1 Patcher Files\vf1fun.dll
    wchar_t *slash = wcsrchr(wide, L'\\');
    if (!slash) return 0;
    *slash = 0;
    wchar_t full[MAX_PATH];
    swprintf(full, MAX_PATH, L"%s\\VF2 Songs\\%hs", wide, name);
    if (GetFileAttributesW(full) == INVALID_FILE_ATTRIBUTES) return 0;
    char narrow[MAX_PATH];
    BOOL lossy = FALSE;
    // The game's path rules decide whether an absolute path is accepted; try that
    // first, then the same file reached from the Sounds folder.
    const char *candidates[2] = { 0, 0 };
    if (WideCharToMultiByte(CP_ACP, 0, full, -1, narrow, MAX_PATH, 0, &lossy) && !lossy)
        candidates[0] = narrow;
    char relative[MAX_PATH];
    sprintf_s(relative, "..\\Virtual Families 1 Patcher Files\\VF2 Songs\\%s", name);
    candidates[1] = relative;
    for (const char *file : candidates) {
        if (!file) continue;
        void *wrapper = GameNew(4);
        if (!wrapper) return 0;
        SoundTrackCtor(wrapper, file);
        if (TrackLoaded(wrapper)) {
#ifdef VF1FUN_TEST_LOG
            char line[400]; sprintf_s(line, "loaded %s via %s\n", name, file == relative ? "relative path" : "absolute path"); TestLog(line);
#endif
            return wrapper;
        }
    }
    return 0;
}

static void PrepareSongs(void *manager) {
    gSongsReady = true;
    static const char *const names[5] = { "menu.ogg", "song1.ogg", "song2.ogg", "song3.ogg", "song4.ogg" };
    for (int i = 0; i < 5; ++i) {
        gVF1Track[i] = ((void **)manager)[i];
        gVF2Track[i] = LoadVF2Track(names[i]);
    }
}

static void __fastcall PlayNextWithVF2Songs(void *manager, void *, bool menu) {
    if (!gSongsReady) PrepareSongs(manager);
    void **slot = (void **)manager;
    void *playing = slot[5];  // +0x14
    for (int i = 0; i < 5; ++i) {
        void *vf2 = gVF2Track[i], *vf1 = gVF1Track[i];
        if (!vf1) continue;
        if (playing && playing == vf1) slot[i] = vf1;
        else if (playing && vf2 && playing == vf2) slot[i] = vf2;
        else slot[i] = (vf2 && GetRandom(2) == 0) ? vf2 : vf1;
    }
    PlayNextStock(manager, menu);
#ifdef VF1FUN_TEST_LOG
    {
        char line[200];
        void *now = slot[5];
        int which = -1; bool vf2now = false;
        for (int i = 0; i < 5; ++i) { if (now == gVF2Track[i] && now) { which = i; vf2now = true; } if (now == gVF1Track[i]) which = i; }
        sprintf_s(line, "play next (menu=%d): now playing slot %d from %s\n", (int)menu, which, vf2now ? "VF2" : "VF1");
        TestLog(line);
    }
#endif
}

static void InstallVF2Songs() {
    for (unsigned site : kPlayNextCallers)
        RetargetCall(site, 0x44C6F0, (void *)&PlayNextWithVF2Songs);
}
