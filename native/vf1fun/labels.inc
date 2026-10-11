// labels.inc -- "Behavior Label Variants" (every variant caption is one the Virtual Families 2 patcher already uses): the caption under a villager ("Action" on the info bar) varies
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
//   Career work: computer 0x45D399 (0x95), kitchen 0x47ED23 (0x101), workshop 0x470FE0 (0x104)
//   Trying to make a baby: strncpy at 0x478DB1 (0x1C0): 'private adult romantic time' for couples that cannot conceive
//   Sandbox                0x460E50 (0xA7); Watering the flower boxes 0x463318 0x4635A8 (0xBB)
//   Board game 0x474A16 (0x6B); Homework 0x46CFA7 (0xA5) 0x46CB2E (0xED)
//   Playing in the pool    0x45F19C 0x465F91 0x466241   (0x9B, 0xCF swimming, 0xD0 splashing)

typedef const char *(__thiscall *GetStringFn2)(void *strings, int id);
static const GetStringFn2 StockGetString = (GetStringFn2)0x44FD90;

struct LabelSet { const char *const *variants; int count; };
static const char *const kTVLabels[] = {
    "Watching a movie",
    "Watching a TV show",
    "Watching a documentary",
    "Watching the news",
    "Watching the weather channel",
    "Watching MovieFlix",
    "Watching cartoons",
    "Watching anime" };
static const char *const kReadingLabels[] = {
    "Reading a novel",
    "Reading a textbook",
    "Reading a comic book",
    "Reading a picture book",
    "Reading a chapter book",
    "Reading manga",
    "Reading a how-to manual" };
static const char *const kWebLabels[] = {
    "Browsing LDWForums",
    "Watching cat videos",
    "Watching memes",
    "Making memes",
    "Posting memes online" };
static const char *const kGameLabels[] = {
    "Playing Virtual Villagers",
    "Playing Virtual Town",
    "Playing Virtual Families",
    "Playing Little Pocket Pet",
    "Playing Fish Tycoon",
    "Playing Plant Tycoon",
    "Playing the Sims",
    "Playing BlockCraft",
    "Playing Earth-rarria",
    "Playing Farmdew Valley",
    "Playing Poptropicals",
    "Playing Club Puffle",
    "Playing PetKinz" };
static const char *const kPoolLabels[] = {
    "Doing laps in the pool",
    "Practicing swimming lessons",
    "Practicing diving technique",
    "Diving underwater",
    "Cannonball!",
    "Diving to the bottom of the pool",
    "Practicing underwater backflips",
    "Practicing underwater frontflips",
    "Practicing underwater handstands",
    "Snorkelling" };
// The nap pool also holds the "needs to sit down" captions (VF2's sit-down group).
static const char *const kSandboxLabels[] = {
    "Making sand sculptures",
    "Digging moats",
    "Digging to the center of the earth" };
static const char *const kFlowerLabels[] = {
    "Gardening",
    "Caring for the Magic Plants" };
static const char *const kBoardGameLabels[] = {
    "Playing chess",
    "Playing checkers" };
static const char *const kHomeworkLabels[] = {
    "Doing math homework",
    "Doing geography homework",
    "Doing biology homework",
    "Doing literature homework",
    "Procrastinating" };
static const char *const kNapLabels[] = {
    "Dreaming of Isola",
    "Dreaming of family",
    "Dreaming of pets",
    "Dreaming of friends",
    "Dreaming of the future",
    "Dreaming of the beach",
    "Dreaming of snow",
    "Dreaming of holidays",
    "Dreaming of vacations",
    "Dreaming of roller coasters",
    "Dreaming of climbing mountains",
    "Dreaming of camping",
    "Dreaming of family trips",
    "Dreaming of the countryside",
    "Dreaming of LDW games",
    "Dreaming of the city",
    "Dreaming of the forest",
    "Dreaming of unicorns",
    "Dreaming of fish",
    "Dreaming of jungles",
    "Dreaming of tropical islands",
    "Dreaming of skyscrapers",
    "Dreaming of floating in space",
    "Dreaming of treasure",
    "Dreaming of getting rich",
    "Dreaming of adventures",
    "Dreaming of swimming",
    "Dreaming of flying",
    "Dreaming of falling",
    "Dreaming of discovering something",
    "Thinking",
    "Taking a moment to reflect",
    "Thinking of family",
    "Thinking of relatives",
    "Thinking of friends",
    "Thinking of pets",
    "Thinking of vacations",
    "Thinking of weekend plans",
    "Thinking of what to watch next",
    "Resting",
    "Resting eyes",
    "Resting feet",
    "Relaxing for a bit",
    "Taking a break",
    "Enjoying life",
    "Enjoying the scenery",
    "Texting",
    "Playing games on phone",
    "Scrolling on phone",
    "Checking social media on phone",
    "Scrapbooking",
    "Texting friends",
    "Texting family",
    "Texting relatives",
    "Thinking of work" };
// Career captions: VF2 uses one list for all three workstations (computer, kitchen, workshop).
// Captions only; the behavior, its weights and the career progression are not touched.
static const char *const kCareerLabels[] = {
    "Practicing career skills",
    "Practicing new work techniques",
    "Working on a job project",
    "Practicing interview skills",
    "Learning new job skills",
    "Practicing a new job skill",
    "Improving job performance",
    "Working on a project for a client",
    "Taking boss' advice on a job project",
    "Reflecting on recent career performance",
    "Trying to improve career performance",
    "Working hard for the next promotion!",
    "Perfecting skills for career",
    "Need to meet a job deadline!",
    "Pursuing further job opportunities",
    "Pursuing personal career goals",
    "Busy working!",
    "Learning new tips and tricks for career",
    "Updating career portfolio",
    "Updating resume",
    "Updating CV" };

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

static const char *__fastcall CareerCaption(void *strings, void *, int id) {
    static const LabelSet set = { kCareerLabels, (int)(sizeof kCareerLabels / sizeof kCareerLabels[0]) };
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

static const char *__fastcall SandboxCaption(void *strings, void *, int id) {
    static const LabelSet set = { kSandboxLabels, (int)(sizeof kSandboxLabels / sizeof kSandboxLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall FlowerCaption(void *strings, void *, int id) {
    static const LabelSet set = { kFlowerLabels, (int)(sizeof kFlowerLabels / sizeof kFlowerLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall BoardGameCaption(void *strings, void *, int id) {
    static const LabelSet set = { kBoardGameLabels, (int)(sizeof kBoardGameLabels / sizeof kBoardGameLabels[0]) };
    return PickLabel(strings, id, set);
}
static const char *__fastcall HomeworkCaption(void *strings, void *, int id) {
    static const LabelSet set = { kHomeworkLabels, (int)(sizeof kHomeworkLabels / sizeof kHomeworkLabels[0]) };
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
        { 0x45D399, (void *)&CareerCaption }, { 0x47ED23, (void *)&CareerCaption }, { 0x470FE0, (void *)&CareerCaption },
        { 0x460E50, (void *)&SandboxCaption },
        { 0x463318, (void *)&FlowerCaption }, { 0x4635A8, (void *)&FlowerCaption },
        { 0x474A16, (void *)&BoardGameCaption },
        { 0x46CFA7, (void *)&HomeworkCaption }, { 0x46CB2E, (void *)&HomeworkCaption },
        { 0x45F19C, (void *)&PoolCaption }, { 0x465F91, (void *)&PoolCaption }, { 0x466241, (void *)&PoolCaption },
    };
    for (const Site &s : sites)
        RetargetCall(s.address, 0x44FD90, s.wrapper);  // only a call that still reaches the stock GetString
    RetargetCall(0x478DB1, 0x4993C0, (void *)&TryingForBabyCopy);
}
