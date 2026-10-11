// labels.inc -- "Behavior Label Variants": the caption under a villager ("Action" on the info bar) varies for a
// set of actions, using ONLY the captions and age rules of the Virtual Families 2 patcher. LABELS ONLY: the
// behaviors, their selection weights, praise training and career progression are not touched.
//
// Each behavior copies its caption into the villager's 40-byte label with
// `strncpy(villager + 0x13594, GetString(id), 0x27)`. At each verified copy the call to strncpy (0x4993C0) is
// retargeted to LabelCopy, which knows the action from its return address and the villager from the
// destination (villager = dest - 0x13594), and writes one of VF2's captions for that action and that
// villager's age instead. The caption is chosen once, when the action starts. Every caption is at most 39
// characters. This file's arrays are generated from the VF2 generator's BEHAVIOR_LABEL_GROUPS.
//
// VF2's age gates (CVillager age in 20-a-year units, as in VF1): web "buying" from 13 (260); teen lists
// from 14 (280); adult lists from 19 (380).

static const char *const kTV[] = {
    "Watching a movie",
    "Watching a TV show",
    "Watching a documentary",
    "Watching the news",
    "Watching the weather channel",
    "Watching MovieFlix",
    "Watching cartoons",
    "Watching anime" };
static const char *const kReading[] = {
    "Reading a novel",
    "Reading a textbook",
    "Reading a comic book",
    "Reading a picture book",
    "Reading a chapter book",
    "Reading manga",
    "Reading a how-to manual" };
static const char *const kWebBasic[] = {
    "Browsing LDWForums",
    "Watching cat videos",
    "Watching memes",
    "Making memes",
    "Posting memes online" };
static const char *const kWeb13Plus[] = {
    "Buying stuff online" };
static const char *const kWebAdult[] = {
    "Browsing Fakebook",
    "Browsing social media",
    "Browsing VideoTube",
    "Browsing ClipTok",
    "Browsing Picstagram",
    "Posting on Fakebook",
    "Posting on social media",
    "Posting on VideoTube",
    "Posting on ClipTok",
    "Posting on Picstagram" };
static const char *const kGame[] = {
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
static const char *const kGameTeen[] = {
    "Playing The Older Scrolls",
    "Playing RimWorld" };
static const char *const kNapDream[] = {
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
    "Dreaming of discovering something" };
static const char *const kSitGeneral[] = {
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
    "Texting relatives" };
static const char *const kSitAdult[] = {
    "Thinking of children",
    "Thinking of grandchildren",
    "Thinking of spouse",
    "Texting spouse" };
static const char *const kSitWork[] = {
    "Thinking of work" };
static const char *const kSitSchool[] = {
    "Thinking of school" };
static const char *const kSitTeenFemale[] = {
    "Texting boyfriend" };
static const char *const kSitTeenMale[] = {
    "Texting girlfriend" };
static const char *const kPoolGeneral[] = {
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
static const char *const kPoolChild[] = {
    "Playing mermaids",
    "Playing pirates",
    "Playing dolphins",
    "Playing sharks" };
static const char *const kSandbox[] = {
    "Making sand sculptures",
    "Digging moats",
    "Digging to the center of the earth" };
static const char *const kFlower[] = {
    "Gardening",
    "Caring for the Magic Plants" };
static const char *const kBoard[] = {
    "Playing chess",
    "Playing checkers" };
static const char *const kTeenHomework[] = {
    "Doing math homework",
    "Doing geography homework",
    "Doing biology homework",
    "Doing literature homework" };
static const char *const kCareer[] = {
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
static const char *const kChildHomework[] = { "Doing homework", "Procrastinating" };
static const char *const kPrivateRomantic[] = { "Having private adult romantic time" };

struct Cands {
    const char *v[160];
    int n;
    Cands() : n(0) {}
    void Add(const char *const *items, int count) { for (int i = 0; i < count && n < 160; ++i) v[n++] = items[i]; }
};
#define ADD(c, a) (c).Add(a, (int)(sizeof a / sizeof a[0]))

enum LabelKind { L_TV, L_READ, L_WEB, L_GAME, L_NAP, L_POOL, L_SAND, L_FLOWER, L_BOARD, L_HOMEWORK, L_CAREER, L_TRYBABY };

static const int kAge13 = 0x104, kAgeTeen = 0x118, kAgeAdult = 0x17C;

static int VillagerAge(const unsigned char *v) { return *(const int *)(v + 0x2A34); }
static bool VillagerHasCareer(const unsigned char *v) { return *(const int *)(v + 0x2B6C) != -1; }
static bool VillagerIsFemale(const unsigned char *v) { return *(const int *)(v + 0x2A38) == 1; }

// VF2ApplySitDownLabelPools: the "needs to sit down" captions by who is sitting.
static void AddSitDown(Cands &c, const unsigned char *v) {
    int age = VillagerAge(v);
    ADD(c, kSitGeneral);
    if (age >= kAgeAdult && VillagerHasCareer(v)) { ADD(c, kSitAdult); ADD(c, kSitWork); }
    else if (age >= kAgeAdult) { ADD(c, kSitAdult); ADD(c, kSitSchool); }
    else if (age >= kAgeTeen) { ADD(c, kSitSchool); if (VillagerIsFemale(v)) c.Add(kSitTeenFemale, 1); else c.Add(kSitTeenMale, 1); }
    else { ADD(c, kSitSchool); }
}

// Private adult romantic time (VF2's approach): the "Trying to make a baby" behavior (string 0x1C0,
// eString_BehaviorGoInHouse, written at 0x478DB1) is not replaced, only its caption, and only for a couple
// that cannot conceive: same-sex, or an opposite-sex couple whose family already has six children. The test
// is the villager's own, every time the caption is written.
static bool PrivateRomanticCouple(const unsigned char *villager) {
    int a = FounderSlot(), b = SpouseSlot();
    return gPrivateRomantic && PrivateCoupleNow() && (villager == Villager(a) || villager == Villager(b));
}

typedef char *(__cdecl *StrncpyFn)(char *dest, const char *src, size_t n);
struct LabelSite { unsigned returnAddress; LabelKind kind; };
// returnAddress = (the strncpy call) + 5, for the copy that writes this action's caption.
static const LabelSite kLabelSites[] = {
    { 0x470C9D + 5, L_TV }, { 0x4789BE + 5, L_TV }, { 0x47EC3F + 5, L_TV },
    { 0x45F669 + 5, L_READ },
    { 0x47EB50 + 5, L_WEB }, { 0x47EB90 + 5, L_WEB },
    { 0x476A58 + 5, L_GAME },
    { 0x45FB08 + 5, L_NAP }, { 0x464D58 + 5, L_NAP },
    { 0x45F1A9 + 5, L_POOL }, { 0x465FA2 + 5, L_POOL }, { 0x466252 + 5, L_POOL },
    { 0x460E61 + 5, L_SAND },
    { 0x463329 + 5, L_FLOWER }, { 0x4635B9 + 5, L_FLOWER },
    { 0x474A27 + 5, L_BOARD },
    { 0x46CFB8 + 5, L_HOMEWORK }, { 0x46CB3B + 5, L_HOMEWORK },
    { 0x45D3AA + 5, L_CAREER }, { 0x47ED34 + 5, L_CAREER }, { 0x470FF1 + 5, L_CAREER },
    { 0x478DB1 + 5, L_TRYBABY },
};

// Captions are cosmetic, so they use their own generator and never advance the game's (GetRandom drives
// deaths and multiple births).
static unsigned gLabelSeed;
static int LabelRandom(int n) {
    if (!gLabelSeed) gLabelSeed = GetTickCount() | 1;
    gLabelSeed = gLabelSeed * 1664525u + 1013904223u;
    return (int)((gLabelSeed >> 8) % (unsigned)n);
}

static char *__cdecl LabelCopy(char *dest, const char *src, size_t n) {
    unsigned ret = (unsigned)_ReturnAddress();
    const unsigned char *v = (const unsigned char *)dest - 0x13594;
    const LabelSite *site = 0;
    for (const LabelSite &s : kLabelSites) if (s.returnAddress == ret) site = &s;
    if (site) {
        Cands c;
        int age = VillagerAge(v);
        switch (site->kind) {
        case L_TV: ADD(c, kTV); break;
        case L_READ: ADD(c, kReading); break;
        case L_WEB:
            ADD(c, kWebBasic);
            if (age >= kAge13) ADD(c, kWeb13Plus);
            if (age >= kAgeTeen) ADD(c, kWebAdult);
            break;
        case L_GAME: ADD(c, kGame); if (age >= kAgeTeen) ADD(c, kGameTeen); break;
        case L_NAP: ADD(c, kNapDream); AddSitDown(c, v); break;
        case L_POOL: ADD(c, kPoolGeneral); if (age < kAgeTeen) ADD(c, kPoolChild); break;
        case L_SAND: ADD(c, kSandbox); break;
        case L_FLOWER: ADD(c, kFlower); break;
        case L_BOARD: ADD(c, kBoard); break;
        case L_HOMEWORK: if (age >= kAgeTeen) ADD(c, kTeenHomework); else ADD(c, kChildHomework); break;
        case L_CAREER: ADD(c, kCareer); break;
        case L_TRYBABY: if (PrivateRomanticCouple(v)) c.Add(kPrivateRomantic, 1); break;
        }
        if (c.n > 0) src = c.v[LabelRandom(c.n)];
    }
    return ((StrncpyFn)0x4993C0)(dest, src, n);
}

// allCaptions: the Behavior Label Variants setting; tryBaby: Private Adult Romantic Time (its caption alone).
static void InstallBehaviorLabelVariants(bool allCaptions, bool tryBaby) {
    for (const LabelSite &s : kLabelSites)
        if (s.kind == L_TRYBABY ? (allCaptions || tryBaby) : allCaptions)
            RetargetCall(s.returnAddress - 5, 0x4993C0, (void *)&LabelCopy);  // only a call that still reaches strncpy
}
