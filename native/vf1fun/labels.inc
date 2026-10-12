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
// from 14 (280); adult lists from 19 (380); the shower, jewelry and sink lists split at 14 (280). Not ported, by the
// owner's choice: VF2's rare Half-Caff coffee and Bubble Bass burger captions.

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
// VF2's kids_table group: what a child at the homework table may be doing.
static const char *const kChildHomework[] = {
    "Doing arts and crafts",
    "Making origami",
    "Coloring in a coloring book",
    "Making clay sculptures",
    "Making charm bracelets",
    "Making necklaces",
    "Doing homework",
    "Procrastinating" };
// VF2 group "drink".
static const char *const kDrink[] = {
    "Drinking soda",
    "Drinking milkshakes",
    "Drinking milk",
    "Drinking juice",
    "Drinking mineral water",
    "Drinking sparkling water",
    "Drinking tea",
    "Drinking an energy drink",
    "Drinking Hydr-Aid",
    "Drinking boba tea" };
// VF2 group "heat_food".
static const char *const kHeatFood[] = {
    "Baking a cake",
    "Heating up leftovers",
    "Baking a pie",
    "Baking cookies",
    "Heating up pizza",
    "Eating takeout" };
// VF2 group "snacks".
static const char *const kSnacks[] = {
    "Eating a bag of chips",
    "Eating pretzels",
    "Eating trail mix",
    "Eating cookies",
    "Eating pizza",
    "Eating popcorn",
    "Eating candy",
    "Drinking soda",
    "Drinking milkshakes",
    "Drinking milk",
    "Drinking juice" };
// VF2 group "meal_prep".
static const char *const kMealPrep[] = {
    "Making sushi",
    "Making Chinese food",
    "Making Mexican food",
    "Making American food",
    "Making vegetarian food",
    "Making Japanese food",
    "Making salad",
    "Making Indian food",
    "Making Turkish Food",
    "Making Spanish food",
    "Making African food",
    "Making Filipino food",
    "Making fish and chips",
    "Making lasagna",
    "Making pasta",
    "Making dim sum",
    "Making pizza",
    "Making French food",
    "Making escargot",
    "Making burgers and fries",
    "Making tacos",
    "Making paella",
    "Making seafood",
    "Making steak au poivre" };
// VF2 group "shower_general".
static const char *const kShowerGeneral[] = {
    "Taking a bath",
    "Taking a bubble bath",
    "Singing in the shower",
    "Taking a relaxing bath",
    "Taking a relaxing bubble bath" };
// VF2 group "shower_adult".
static const char *const kShowerAdult[] = {
    "Having a spa day" };
// VF2 group "shower_child".
static const char *const kShowerChild[] = {
    "Playing with bath toys" };
// VF2 group "bathroom_sink_general".
static const char *const kSinkGeneral[] = {
    "Putting on face mask",
    "Trimming nails",
    "Applying lotion",
    "Applying sunscreen" };
// VF2 group "bathroom_sink_grooming".
static const char *const kSinkGrooming[] = {
    "Painting fingernails",
    "Painting toenails",
    "Doing a manicure",
    "Doing a pedicure",
    "Putting on makeup" };
// VF2 group "bathroom_sink_female_teen_plus".
static const char *const kSinkJewelry[] = {
    "Putting on jewelry" };
// VF2 group "coffee".
static const char *const kCoffee[] = {
    "Making espresso",
    "Making a latte",
    "Making a matcha latte",
    "Making a caffe mocha",
    "Making an americano",
    "Making a ristretto",
    "Making a double-shot espresso",
    "Making black coffee",
    "Making cappuccino",
    "Making frozen coffee",
    "Making iced coffee",
    "Making a frappe",
    "Making tea",
    "Making matcha tea",
    "Making earl grey tea",
    "Making jasmine tea",
    "Making black tea",
    "Making iced tea" };
// VF2 group "coffee_evening".
static const char *const kCoffeeEvening[] = {
    "Making chamomile tea" };
// VF2 group "telescope".
static const char *const kTelescope[] = {
    "Finding constellations",
    "Finding planets",
    "Looking for aliens",
    "Practicing astronomy",
    "Finding space stations",
    "Finding the ISS",
    "Looking for rocket ships",
    "Looking for meteors",
    "Trying to find shooting stars",
    "Looking for comets" };
// VF2 group "teen_online_test".
static const char *const kOnlineTest[] = {
    "Applying for volunteer opportunities",
    "Planning career path",
    "Looking for schools to apply to",
    "Exploring future career opportunities",
    "Exploring volunteer opportunities" };
// The two captions VF2 sets for the patio table's drinks (VF2RunMobilePreparingDrinks, VF2RunMobileDrinkAtPatioChair).
static const char *const kPatioDrinks[] = {
    "Getting some drinks",
    "Having a refreshing drink" };
static const char *const kPrivateRomantic[] = { "Having private adult romantic time" };

struct Cands {
    const char *v[160];
    int n;
    Cands() : n(0) {}
    void Add(const char *const *items, int count) { for (int i = 0; i < count && n < 160; ++i) v[n++] = items[i]; }
};
#define ADD(c, a) (c).Add(a, (int)(sizeof a / sizeof a[0]))

enum LabelKind { L_TV, L_READ, L_WEB, L_GAME, L_NAP, L_POOL, L_SAND, L_FLOWER, L_BOARD, L_HOMEWORK, L_CAREER, L_TRYBABY, L_SITDOWN,
                 L_DRINK, L_HEATFOOD, L_SNACKS, L_MEAL, L_SHOWER, L_SINKFACE, L_SINKGROOM, L_COFFEE, L_STARS, L_ONLINETEST, L_PATIO };

static const int kAge13 = 0x104, kAgeTeen = 0x118, kAgeAdult = 0x17C;

static int VillagerAge(const unsigned char *v) { return *(const int *)(v + 0x2A34); }
static bool VillagerHasCareer(const unsigned char *v) { return *(const int *)(v + 0x2B6C) != -1; }
static bool VillagerIsFemale(const unsigned char *v) { return *(const int *)(v + 0x2A38) == 1; }

// VF2ApplySitDownLabelPools: the sit-down captions by who is sitting. As in VF2 they go only on the game's own
// "Needs to sit down" action (eSayNeedSitDown, written at 0x47AC21); naps keep the dream captions.
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

// Captions are cosmetic, so they use their own generator and never advance the game's (GetRandom drives
// deaths and multiple births).
static unsigned gLabelSeed;
static int LabelRandom(int n) {
    if (!gLabelSeed) gLabelSeed = GetTickCount() | 1;
    gLabelSeed = gLabelSeed * 1664525u + 1013904223u;
    return (int)((gLabelSeed >> 8) % (unsigned)n);
}

// VF2ApplyShowerLabel: a child (under 14) gets the general list and the child list; anyone older the general list
// and the adult list.
static void AddShower(Cands &c, const unsigned char *v) {
    ADD(c, kShowerGeneral);
    if (VillagerAge(v) < kAgeTeen) ADD(c, kShowerChild); else ADD(c, kShowerAdult);
}

// VF2CanPutOnJewelry: a girl or woman from 14.
static bool CanPutOnJewelry(const unsigned char *v) { return VillagerIsFemale(v) && VillagerAge(v) >= kAgeTeen; }

// VF2ApplyBathroomSinkGeneralLabel: the face/hands washing. General list, plus the jewelry caption for a girl or
// woman from 14.
static void AddSinkGeneral(Cands &c, const unsigned char *v) {
    ADD(c, kSinkGeneral);
    if (CanPutOnJewelry(v)) ADD(c, kSinkJewelry);
}

// VF2ApplyBathroomSinkGroomingLabel: the grooming actions. Anyone who is not female gets only the general list; a
// female gets general + grooming, and from 14 the jewelry caption as well.
static void AddSinkGrooming(Cands &c, const unsigned char *v) {
    ADD(c, kSinkGeneral);
    if (!VillagerIsFemale(v)) return;
    ADD(c, kSinkGrooming);
    if (CanPutOnJewelry(v)) ADD(c, kSinkJewelry);
}

// VF2ApplyCoffeeLabel: by day, or at night 4 times in 5, the coffee list; otherwise (1 in 5 at night) the evening
// list. VF2's rare Half-Caff caption is not ported (owner's exclusion). VF1's day test is CNight 0x491630.
static void AddCoffee(Cands &c) {
    if (IsDayTime(Night) || LabelRandom(5) != 0) ADD(c, kCoffee); else ADD(c, kCoffeeEvening);
}

typedef char *(__cdecl *StrncpyFn)(char *dest, const char *src, size_t n);
struct LabelSite { unsigned returnAddress; LabelKind kind; };
// returnAddress = (the strncpy call) + 5, for the copy that writes this action's caption.
static const LabelSite kLabelSites[] = {
    { 0x4706B5 + 5, L_TV }, { 0x4707D5 + 5, L_TV }, { 0x4708F5 + 5, L_TV }, { 0x4709D5 + 5, L_TV },
    { 0x470AB5 + 5, L_TV }, { 0x470BC5 + 5, L_TV }, { 0x470C9D + 5, L_TV }, { 0x4789BE + 5, L_TV },
    { 0x47EC3F + 5, L_TV },
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
    { 0x47AC21 + 5, L_SITDOWN },
    // Added from the vanilla scan of strncpy into +0x13594 (dataf1_verified.json):
    { 0x45BBE1 + 5, L_DRINK },                                      // Getting a drink (VF2 GetADrink)
    { 0x47E781 + 5, L_HEATFOOD },                                   // Heating up some food (VF2 HeatUpFood)
    { 0x45CD1D + 5, L_SNACKS }, { 0x45CE9D + 5, L_SNACKS }, { 0x45CFFD + 5, L_SNACKS },  // Looking for snacks (LookingForSnacks0/1/2)
    { 0x47C612 + 5, L_MEAL },                                       // Preparing a meal (VF2 PreparingAMeal)
    { 0x45FA18 + 5, L_SHOWER },                                     // Taking a shower (VF2 Shower)
    { 0x467139 + 5, L_SINKFACE },                                   // Washing face / hands at the bathroom sink
    { 0x467402 + 5, L_SINKGROOM }, { 0x467D8C + 5, L_SINKGROOM },   // Putting on lotion/makeup/...; Shaving / Removing makeup
    { 0x469F71 + 5, L_COFFEE }, { 0x46AB81 + 5, L_COFFEE },         // Making coffee; Making a grande latte
    { 0x4741A8 + 5, L_STARS },                                      // Looking for a falling star / Admiring stars in the sky
    { 0x46D4E8 + 5, L_ONLINETEST },                                 // Taking an online test (VF2 TeenOnlineExam)
    { 0x45FE58 + 5, L_PATIO },                                      // Enjoying the patio
};

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
        case L_NAP: ADD(c, kNapDream); break;
        case L_SITDOWN: AddSitDown(c, v); break;
        case L_POOL: ADD(c, kPoolGeneral); if (age < kAgeTeen) ADD(c, kPoolChild); break;
        case L_SAND: ADD(c, kSandbox); break;
        case L_FLOWER: ADD(c, kFlower); break;
        case L_BOARD: ADD(c, kBoard); break;
        case L_HOMEWORK: if (age >= kAgeTeen) ADD(c, kTeenHomework); else ADD(c, kChildHomework); break;
        case L_CAREER: ADD(c, kCareer); break;
        case L_DRINK: ADD(c, kDrink); break;
        case L_HEATFOOD: ADD(c, kHeatFood); break;
        case L_SNACKS: ADD(c, kSnacks); break;
        case L_MEAL: ADD(c, kMealPrep); break;
        case L_SHOWER: AddShower(c, v); break;
        case L_SINKFACE: AddSinkGeneral(c, v); break;
        case L_SINKGROOM: AddSinkGrooming(c, v); break;
        case L_COFFEE: AddCoffee(c); break;
        case L_STARS: ADD(c, kTelescope); break;
        case L_ONLINETEST: ADD(c, kOnlineTest); break;
        case L_PATIO: AddSitDown(c, v); ADD(c, kPatioDrinks); break;
        case L_TRYBABY: if (PrivateRomanticCouple(v)) c.Add(kPrivateRomantic, 1); break;
        }
        // VF2ApplyRememberedOrRandomLabel: one roll out of (count + 1); 0 keeps the game's own caption.
        // The private romantic caption is not a variant: it always replaces "Trying to make a baby".
        if (site->kind == L_TRYBABY) { if (c.n > 0) src = c.v[0]; }
        else if (c.n > 0) { int r = LabelRandom(c.n + 1); if (r) src = c.v[r - 1]; }
    }
    char *r = ((StrncpyFn)0x4993C0)(dest, src, n);
    if (n == 0x27) dest[n] = 0;  // the 40-byte label: 0x27 characters and a terminator (a 39-character caption fills it)
    return r;
}

// allCaptions: the Behavior Label Variants setting; tryBaby: Private Adult Romantic Time (its caption alone).
static void InstallBehaviorLabelVariants(bool allCaptions, bool tryBaby) {
    for (const LabelSite &s : kLabelSites)
        if (s.kind == L_TRYBABY ? (allCaptions || tryBaby) : allCaptions)
            RetargetCall(s.returnAddress - 5, 0x4993C0, (void *)&LabelCopy);  // only a call that still reaches strncpy
}
