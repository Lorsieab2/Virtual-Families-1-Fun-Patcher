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
//   Working at the computer 0x45D399                     (0x95), kitchen career 0x47ED23 (0x101), workshop 0x470FE0 (0x104)
//   Trying to make a baby: strncpy at 0x478DB1 (0x1C0): 'private adult romantic time' for couples that cannot conceive
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
// The nap pool also holds the "needs to sit down" captions (VF2's sit-down group).
static const char *const kNapLabels[] = { "Dozing off on the couch", "Dreaming of family", "Dreaming of the beach",
    "Dreaming of the future", "Dreaming of holidays", "Resting for a while", "Resting", "Resting eyes", "Resting feet",
    "Relaxing for a bit", "Taking a break", "Enjoying life", "Enjoying the scenery", "Thinking of work",
    "Thinking of vacations", "Thinking of weekend plans", "Thinking of what to watch next", "Texting friends" };
// Careers: captions only; the behavior, its weights and the career progression are not touched.
static const char *const kOfficeLabels[] = { "Working on a spreadsheet", "Writing a report", "Answering email",
    "Typing up a proposal", "Planning a presentation", "Reviewing the numbers" };
static const char *const kKitchenLabels[] = { "Making pasta", "Making pizza", "Making salad", "Baking a cake", "Baking cookies",
    "Making lasagna", "Making tacos", "Making sushi" };
static const char *const kWorkshopLabels[] = { "Building a birdhouse", "Sanding a board", "Fixing a gadget",
    "Sawing planks", "Tinkering with parts", "Measuring twice" };

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

static const char *__fastcall OfficeCaption(void *strings, void *, int id) {
    static const LabelSet set = { kOfficeLabels, (int)(sizeof kOfficeLabels / sizeof kOfficeLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall KitchenCaption(void *strings, void *, int id) {
    static const LabelSet set = { kKitchenLabels, (int)(sizeof kKitchenLabels / sizeof kKitchenLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall WorkshopCaption(void *strings, void *, int id) {
    static const LabelSet set = { kWorkshopLabels, (int)(sizeof kWorkshopLabels / sizeof kWorkshopLabels[0]) };
    return PickLabel(strings, id, set);
}

// Private adult romantic time (VF2's approach): the "Trying to make a baby" behavior is not replaced,
// only its caption varies, and the test is the villager's own: a couple that cannot conceive, which is
// exactly the couple the pregnancy rules (and the six-child drop patch) treat as "private": same-sex, or
// an opposite-sex couple whose family already has six children. It is computed from the acting villager
// every time the caption is written. Only the "Trying to make a baby" caption varies (string 0x1C0,
// eString_BehaviorGoInHouse), written by `strncpy(villager + 0x13594, text, 0x27)` at 0x478DB1, so the
// villager is `dest - 0x13594`.
static bool PrivateRomanticCouple(unsigned char *villager) {
    int a = FounderSlot(), b = SpouseSlot();
    return PrivateCoupleNow() && (villager == Villager(a) || villager == Villager(b));
}
typedef char *(__cdecl *StrncpyFn)(char *dest, const char *src, size_t n);
static char *__cdecl TryingForBabyCopy(char *dest, const char *src, size_t n) {
    if (PrivateRomanticCouple((unsigned char *)dest - 0x13594))
        src = "Having private adult romantic time";
    return ((StrncpyFn)0x4993C0)(dest, src, n);
}

static void InstallBehaviorLabelVariants() {
    struct Site { unsigned address; void *wrapper; };
    const Site sites[] = {
        { 0x470C8C, (void *)&TVCaption }, { 0x4789AD, (void *)&TVCaption }, { 0x47EC32, (void *)&TVCaption },
        { 0x45F658, (void *)&ReadingCaption },
        { 0x47EB3F, (void *)&WebCaption }, { 0x47EB7F, (void *)&WebCaption },
        { 0x476A47, (void *)&GameCaption },
        { 0x45FAF7, (void *)&NapCaption }, { 0x464D47, (void *)&NapCaption },
        { 0x45D399, (void *)&OfficeCaption }, { 0x47ED23, (void *)&KitchenCaption }, { 0x470FE0, (void *)&WorkshopCaption },
        { 0x45F19C, (void *)&PoolCaption }, { 0x465F91, (void *)&PoolCaption }, { 0x466241, (void *)&PoolCaption },
    };
    for (const Site &s : sites)
        RetargetCall(s.address, 0x44FD90, s.wrapper);  // only a call that still reaches the stock GetString
    RetargetCall(0x478DB1, 0x4993C0, (void *)&TryingForBabyCopy);
}
