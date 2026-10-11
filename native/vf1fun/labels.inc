// labels.inc -- "Behavior Label Variants": the caption under a villager ("Action" on the info bar) varies
// for a few actions, as in the Virtual Families 2 patcher. LABELS ONLY: the behaviors, their selection
// weights, praise training and career progression are not touched.
//
// Each behavior copies its caption into the villager's 40-byte label (villager +0x13594) with
// `strncpy(label, theStringManager::GetString(id), 0x27)`. At each verified call site the call to
// GetString (0x44FD90) is retargeted to a wrapper that returns one of this action's variants (or the
// stock caption) instead. The variant is chosen once, when the action starts. Every caption is at
// most 39 characters.
//
// Sites (all confirmed by disassembly to be the label write of that action):
//   Watching TV            0x470C8C 0x4789AD 0x47EC32   (string 0x60)
//   Reading a magazine     0x45F658                     (0x9C)
//   Browsing the web       0x47EB3F 0x47EB7F            (0x3D0)
//   Playing video games    0x476A47                     (0x10D)
//   Taking a nap           0x45FAF7 0x464D47            (0x9F)
//   Playing in the pool    0x45F19C 0x465F91 0x466241   (0x9B, 0xCF swimming, 0xD0 splashing)

typedef const char *(__thiscall *GetStringFn2)(void *strings, int id);
static const GetStringFn2 StockGetString = (GetStringFn2)0x44FD90;

struct LabelSet { const char *const *variants; int count; };
static const char *const kTVLabels[] = { "Watching a movie", "Watching a TV show", "Watching a documentary", "Watching the news",
    "Watching the weather channel", "Watching cartoons" };
static const char *const kReadingLabels[] = { "Reading a novel", "Reading a textbook", "Reading a comic book",
    "Reading a picture book", "Reading a chapter book", "Reading a how-to manual" };
static const char *const kWebLabels[] = { "Browsing a forum", "Watching cat videos", "Watching memes", "Making memes",
    "Reading the news online", "Shopping online" };
static const char *const kGameLabels[] = { "Playing a puzzle game", "Playing a racing game", "Playing a farming game",
    "Playing a building game", "Playing an adventure game", "Playing a pet game" };
static const char *const kPoolLabels[] = { "Doing laps in the pool", "Practicing swimming lessons", "Practicing diving technique",
    "Diving underwater", "Cannonball!", "Diving to the bottom of the pool", "Practicing underwater backflips",
    "Practicing underwater handstands", "Snorkelling" };
static const char *const kNapLabels[] = { "Dozing off on the couch", "Dreaming of family", "Dreaming of the beach",
    "Dreaming of the future", "Dreaming of holidays", "Resting for a while" };

// The stock caption is one of the choices, so the original text still appears some of the time.
static const char *PickLabel(void *strings, int id, const LabelSet &set) {
    int pick = GetRandom(set.count + 1);
    return pick == set.count ? StockGetString(strings, id) : set.variants[pick];
}

static const char *__fastcall TVCaption(void *strings, void *, int id) {
    static const LabelSet set = { kTVLabels, (int)(sizeof kTVLabels / sizeof kTVLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall ReadingCaption(void *strings, void *, int id) {
    static const LabelSet set = { kReadingLabels, (int)(sizeof kReadingLabels / sizeof kReadingLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall WebCaption(void *strings, void *, int id) {
    static const LabelSet set = { kWebLabels, (int)(sizeof kWebLabels / sizeof kWebLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall GameCaption(void *strings, void *, int id) {
    static const LabelSet set = { kGameLabels, (int)(sizeof kGameLabels / sizeof kGameLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall NapCaption(void *strings, void *, int id) {
    static const LabelSet set = { kNapLabels, (int)(sizeof kNapLabels / sizeof kNapLabels[0]) };
    return PickLabel(strings, id, set);
}

static const char *__fastcall PoolCaption(void *strings, void *, int id) {
    static const LabelSet set = { kPoolLabels, (int)(sizeof kPoolLabels / sizeof kPoolLabels[0]) };
    return PickLabel(strings, id, set);
}

static void InstallBehaviorLabelVariants() {
    struct Site { unsigned address; void *wrapper; };
    const Site sites[] = {
        { 0x470C8C, (void *)&TVCaption }, { 0x4789AD, (void *)&TVCaption }, { 0x47EC32, (void *)&TVCaption },
        { 0x45F658, (void *)&ReadingCaption },
        { 0x47EB3F, (void *)&WebCaption }, { 0x47EB7F, (void *)&WebCaption },
        { 0x476A47, (void *)&GameCaption },
        { 0x45FAF7, (void *)&NapCaption }, { 0x464D47, (void *)&NapCaption },
        { 0x45F19C, (void *)&PoolCaption }, { 0x465F91, (void *)&PoolCaption }, { 0x466241, (void *)&PoolCaption },
    };
    for (const Site &s : sites)
        RetargetCall(s.address, 0x44FD90, s.wrapper);  // only a call that still reaches the stock GetString
}
