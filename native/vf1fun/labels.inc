// labels.inc -- "Behavior Label Variants": the caption under a villager ("Action" on the info bar) varies for a
// set of actions, using ONLY the captions and age rules of the Virtual Families 2 patcher. This file changes
// LABELS ONLY. The same setting also chooses the computer's web and video-game activities 50:50, as VF2's
// Behavior Patches does, without writing any weight; that lives in computer.inc. Nothing else (behaviors,
// selection weights, career progression) is touched.
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
    TR_NA(39, "Watching a movie"),
    TR_NA(39, "Watching a TV show"),
    TR_NA(39, "Watching a documentary"),
    TR_NA(39, "Watching the news"),
    TR_NA(39, "Watching the weather channel"),
    TR_NA(39, "Watching MovieFlix"),
    TR_NA(39, "Watching cartoons"),
    TR_NA(39, "Watching anime") };
static const char *const kReading[] = {
    TR_NA(39, "Reading a novel"),
    TR_NA(39, "Reading a textbook"),
    TR_NA(39, "Reading a comic book"),
    TR_NA(39, "Reading a picture book"),
    TR_NA(39, "Reading a chapter book"),
    TR_NA(39, "Reading manga"),
    TR_NA(39, "Reading a how-to manual") };
static const char *const kWebBasic[] = {
    TR_NA(39, "Browsing LDWForums"),
    TR_NA(39, "Watching cat videos"),
    TR_NA(39, "Watching memes"),
    TR_NA(39, "Making memes"),
    TR_NA(39, "Posting memes online") };
static const char *const kWeb13Plus[] = {
    TR_NA(39, "Buying stuff online") };
static const char *const kWebAdult[] = {
    TR_NA(39, "Browsing Fakebook"),
    TR_NA(39, "Browsing social media"),
    TR_NA(39, "Browsing VideoTube"),
    TR_NA(39, "Browsing ClipTok"),
    TR_NA(39, "Browsing Picstagram"),
    TR_NA(39, "Posting on Fakebook"),
    TR_NA(39, "Posting on social media"),
    TR_NA(39, "Posting on VideoTube"),
    TR_NA(39, "Posting on ClipTok"),
    TR_NA(39, "Posting on Picstagram") };
static const char *const kGame[] = {
    TR_NA(39, "Playing Virtual Villagers"),
    TR_NA(39, "Playing Virtual Town"),
    TR_NA(39, "Playing Virtual Families"),
    TR_NA(39, "Playing Little Pocket Pet"),
    TR_NA(39, "Playing Fish Tycoon"),
    TR_NA(39, "Playing Plant Tycoon"),
    TR_NA(39, "Playing the Sims"),
    TR_NA(39, "Playing BlockCraft"),
    TR_NA(39, "Playing Earth-rarria"),
    TR_NA(39, "Playing Farmdew Valley"),
    TR_NA(39, "Playing Poptropicals"),
    TR_NA(39, "Playing Club Puffle"),
    TR_NA(39, "Playing PetKinz") };
static const char *const kGameTeen[] = {
    TR_NA(39, "Playing The Older Scrolls"),
    TR_NA(39, "Playing RimWorld") };
static const char *const kNapDream[] = {
    TR_NA(39, "Dreaming of Isola"),
    TR_NA(39, "Dreaming of family"),
    TR_NA(39, "Dreaming of pets"),
    TR_NA(39, "Dreaming of friends"),
    TR_NA(39, "Dreaming of the future"),
    TR_NA(39, "Dreaming of the beach"),
    TR_NA(39, "Dreaming of snow"),
    TR_NA(39, "Dreaming of holidays"),
    TR_NA(39, "Dreaming of vacations"),
    TR_NA(39, "Dreaming of roller coasters"),
    TR_NA(39, "Dreaming of climbing mountains"),
    TR_NA(39, "Dreaming of camping"),
    TR_NA(39, "Dreaming of family trips"),
    TR_NA(39, "Dreaming of the countryside"),
    TR_NA(39, "Dreaming of LDW games"),
    TR_NA(39, "Dreaming of the city"),
    TR_NA(39, "Dreaming of the forest"),
    TR_NA(39, "Dreaming of unicorns"),
    TR_NA(39, "Dreaming of fish"),
    TR_NA(39, "Dreaming of jungles"),
    TR_NA(39, "Dreaming of tropical islands"),
    TR_NA(39, "Dreaming of skyscrapers"),
    TR_NA(39, "Dreaming of floating in space"),
    TR_NA(39, "Dreaming of treasure"),
    TR_NA(39, "Dreaming of getting rich"),
    TR_NA(39, "Dreaming of adventures"),
    TR_NA(39, "Dreaming of swimming"),
    TR_NA(39, "Dreaming of flying"),
    TR_NA(39, "Dreaming of falling"),
    TR_NA(39, "Dreaming of discovering something") };
static const char *const kSitGeneral[] = {
    TR_NA(39, "Thinking"),
    TR_NA(39, "Taking a moment to reflect"),
    TR_NA(39, "Thinking of family"),
    TR_NA(39, "Thinking of relatives"),
    TR_NA(39, "Thinking of friends"),
    TR_NA(39, "Thinking of pets"),
    TR_NA(39, "Thinking of vacations"),
    TR_NA(39, "Thinking of weekend plans"),
    TR_NA(39, "Thinking of what to watch next"),
    TR_NA(39, "Resting"),
    TR_NA(39, "Resting eyes"),
    TR_NA(39, "Resting feet"),
    TR_NA(39, "Relaxing for a bit"),
    TR_NA(39, "Taking a break"),
    TR_NA(39, "Enjoying life"),
    TR_NA(39, "Enjoying the scenery"),
    TR_NA(39, "Texting"),
    TR_NA(39, "Playing games on phone"),
    TR_NA(39, "Scrolling on phone"),
    TR_NA(39, "Checking social media on phone"),
    TR_NA(39, "Scrapbooking"),
    TR_NA(39, "Texting friends"),
    TR_NA(39, "Texting family"),
    TR_NA(39, "Texting relatives") };
static const char *const kSitAdult[] = {
    TR_NA(39, "Thinking of children"),
    TR_NA(39, "Thinking of grandchildren"),
    TR_NA(39, "Thinking of spouse"),
    TR_NA(39, "Texting spouse") };
static const char *const kSitWork[] = {
    TR_NA(39, "Thinking of work") };
static const char *const kSitSchool[] = {
    TR_NA(39, "Thinking of school") };
static const char *const kSitTeenFemale[] = {
    TR_NA(39, "Texting boyfriend") };
static const char *const kSitTeenMale[] = {
    TR_NA(39, "Texting girlfriend") };
static const char *const kPoolGeneral[] = {
    TR_NA(39, "Doing laps in the pool"),
    TR_NA(39, "Practicing swimming lessons"),
    TR_NA(39, "Practicing diving technique"),
    TR_NA(39, "Diving underwater"),
    TR_NA(39, "Cannonball!"),
    TR_NA(39, "Diving to the bottom of the pool"),
    TR_NA(39, "Practicing underwater backflips"),
    TR_NA(39, "Practicing underwater frontflips"),
    TR_NA(39, "Practicing underwater handstands"),
    TR_NA(39, "Snorkelling") };
static const char *const kPoolChild[] = {
    TR_NA(39, "Playing mermaids"),
    TR_NA(39, "Playing pirates"),
    TR_NA(39, "Playing dolphins"),
    TR_NA(39, "Playing sharks") };
static const char *const kSandbox[] = {
    TR_NA(39, "Making sand sculptures"),
    TR_NA(39, "Digging moats"),
    TR_NA(39, "Digging to the center of the earth") };
static const char *const kFlower[] = {
    TR_NA(39, "Gardening"),
    TR_NA(39, "Caring for the Magic Plants") };
static const char *const kBoard[] = {
    TR_NA(39, "Playing chess"),
    TR_NA(39, "Playing checkers") };
static const char *const kTeenHomework[] = {
    TR_NA(39, "Doing math homework"),
    TR_NA(39, "Doing geography homework"),
    TR_NA(39, "Doing biology homework"),
    TR_NA(39, "Doing literature homework") };
static const char *const kCareer[] = {
    TR_NA(39, "Practicing career skills"),
    TR_NA(39, "Practicing new work techniques"),
    TR_NA(39, "Working on a job project"),
    TR_NA(39, "Practicing interview skills"),
    TR_NA(39, "Learning new job skills"),
    TR_NA(39, "Practicing a new job skill"),
    TR_NA(39, "Improving job performance"),
    TR_NA(39, "Working on a project for a client"),
    TR_NA(39, "Taking boss' advice on a job project"),
    TR_NA(39, "Reflecting on recent career performance"),
    TR_NA(39, "Trying to improve career performance"),
    TR_NA(39, "Working hard for the next promotion!"),
    TR_NA(39, "Perfecting skills for career"),
    TR_NA(39, "Need to meet a job deadline!"),
    TR_NA(39, "Pursuing further job opportunities"),
    TR_NA(39, "Pursuing personal career goals"),
    TR_NA(39, "Busy working!"),
    TR_NA(39, "Learning new tips and tricks for career"),
    TR_NA(39, "Updating career portfolio"),
    TR_NA(39, "Updating resume"),
    TR_NA(39, "Updating CV") };
// VF2's kids_table group: what a child at the homework table may be doing.
static const char *const kChildHomework[] = {
    TR_NA(39, "Doing arts and crafts"),
    TR_NA(39, "Making origami"),
    TR_NA(39, "Coloring in a coloring book"),
    TR_NA(39, "Making clay sculptures"),
    TR_NA(39, "Making charm bracelets"),
    TR_NA(39, "Making necklaces"),
    TR_NA(39, "Doing homework"),
    TR_NA(39, "Procrastinating") };
// VF2 group "drink".
static const char *const kDrink[] = {
    TR_NA(39, "Drinking soda"),
    TR_NA(39, "Drinking milkshakes"),
    TR_NA(39, "Drinking milk"),
    TR_NA(39, "Drinking juice"),
    TR_NA(39, "Drinking mineral water"),
    TR_NA(39, "Drinking sparkling water"),
    TR_NA(39, "Drinking tea"),
    TR_NA(39, "Drinking an energy drink"),
    TR_NA(39, "Drinking Hydr-Aid"),
    TR_NA(39, "Drinking boba tea") };
// VF2 group "heat_food".
static const char *const kHeatFood[] = {
    TR_NA(39, "Baking a cake"),
    TR_NA(39, "Heating up leftovers"),
    TR_NA(39, "Baking a pie"),
    TR_NA(39, "Baking cookies"),
    TR_NA(39, "Heating up pizza"),
    TR_NA(39, "Eating takeout") };
// VF2 group "snacks".
static const char *const kSnacks[] = {
    TR_NA(39, "Eating a bag of chips"),
    TR_NA(39, "Eating pretzels"),
    TR_NA(39, "Eating trail mix"),
    TR_NA(39, "Eating cookies"),
    TR_NA(39, "Eating pizza"),
    TR_NA(39, "Eating popcorn"),
    TR_NA(39, "Eating candy"),
    TR_NA(39, "Drinking soda"),
    TR_NA(39, "Drinking milkshakes"),
    TR_NA(39, "Drinking milk"),
    TR_NA(39, "Drinking juice") };
// VF2 group "meal_prep".
static const char *const kMealPrep[] = {
    TR_NA(39, "Making sushi"),
    TR_NA(39, "Making Chinese food"),
    TR_NA(39, "Making Mexican food"),
    TR_NA(39, "Making American food"),
    TR_NA(39, "Making vegetarian food"),
    TR_NA(39, "Making Japanese food"),
    TR_NA(39, "Making salad"),
    TR_NA(39, "Making Indian food"),
    TR_NA(39, "Making Turkish Food"),
    TR_NA(39, "Making Spanish food"),
    TR_NA(39, "Making African food"),
    TR_NA(39, "Making Filipino food"),
    TR_NA(39, "Making fish and chips"),
    TR_NA(39, "Making lasagna"),
    TR_NA(39, "Making pasta"),
    TR_NA(39, "Making dim sum"),
    TR_NA(39, "Making pizza"),
    TR_NA(39, "Making French food"),
    TR_NA(39, "Making escargot"),
    TR_NA(39, "Making burgers and fries"),
    TR_NA(39, "Making tacos"),
    TR_NA(39, "Making paella"),
    TR_NA(39, "Making seafood"),
    TR_NA(39, "Making steak au poivre") };
// VF2 group "shower_general".
static const char *const kShowerGeneral[] = {
    TR_NA(39, "Taking a bath"),
    TR_NA(39, "Taking a bubble bath"),
    TR_NA(39, "Singing in the shower"),
    TR_NA(39, "Taking a relaxing bath"),
    TR_NA(39, "Taking a relaxing bubble bath") };
// VF2 group "shower_adult".
static const char *const kShowerAdult[] = {
    TR_NA(39, "Having a spa day") };
// VF2 group "shower_child".
static const char *const kShowerChild[] = {
    TR_NA(39, "Playing with bath toys") };
// VF2 group "bathroom_sink_general".
static const char *const kSinkGeneral[] = {
    TR_NA(39, "Putting on face mask"),
    TR_NA(39, "Trimming nails"),
    TR_NA(39, "Applying lotion"),
    TR_NA(39, "Applying sunscreen") };
// VF2 group "bathroom_sink_grooming".
static const char *const kSinkGrooming[] = {
    TR_NA(39, "Painting fingernails"),
    TR_NA(39, "Painting toenails"),
    TR_NA(39, "Doing a manicure"),
    TR_NA(39, "Doing a pedicure"),
    TR_NA(39, "Putting on makeup") };
// VF2 group "bathroom_sink_female_teen_plus".
static const char *const kSinkJewelry[] = {
    TR_NA(39, "Putting on jewelry") };
// VF2 group "coffee".
static const char *const kCoffee[] = {
    TR_NA(39, "Making espresso"),
    TR_NA(39, "Making a latte"),
    TR_NA(39, "Making a matcha latte"),
    TR_NA(39, "Making a caffe mocha"),
    TR_NA(39, "Making an americano"),
    TR_NA(39, "Making a ristretto"),
    TR_NA(39, "Making a double-shot espresso"),
    TR_NA(39, "Making black coffee"),
    TR_NA(39, "Making cappuccino"),
    TR_NA(39, "Making frozen coffee"),
    TR_NA(39, "Making iced coffee"),
    TR_NA(39, "Making a frappe"),
    TR_NA(39, "Making tea"),
    TR_NA(39, "Making matcha tea"),
    TR_NA(39, "Making earl grey tea"),
    TR_NA(39, "Making jasmine tea"),
    TR_NA(39, "Making black tea"),
    TR_NA(39, "Making iced tea") };
// VF2 group "coffee_evening".
static const char *const kCoffeeEvening[] = {
    TR_NA(39, "Making chamomile tea") };
// VF2 group "telescope".
static const char *const kTelescope[] = {
    TR_NA(39, "Finding constellations"),
    TR_NA(39, "Finding planets"),
    TR_NA(39, "Looking for aliens"),
    TR_NA(39, "Practicing astronomy"),
    TR_NA(39, "Finding space stations"),
    TR_NA(39, "Finding the ISS"),
    TR_NA(39, "Looking for rocket ships"),
    TR_NA(39, "Looking for meteors"),
    TR_NA(39, "Trying to find shooting stars"),
    TR_NA(39, "Looking for comets") };
// VF2 group "teen_online_test".
static const char *const kOnlineTest[] = {
    TR_NA(39, "Applying for volunteer opportunities"),
    TR_NA(39, "Planning career path"),
    TR_NA(39, "Looking for schools to apply to"),
    TR_NA(39, "Exploring future career opportunities"),
    TR_NA(39, "Exploring volunteer opportunities") };
// The two captions VF2 sets for the patio table's drinks (VF2RunMobilePreparingDrinks, VF2RunMobileDrinkAtPatioChair).
static const char *const kPatioDrinks[] = {
    TR_NA(39, "Getting some drinks"),
    TR_NA(39, "Having a refreshing drink") };
static const char *const kPrivateRomantic[] = { TR_NA(39, "Having private adult romantic time") };

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
        // A caption of ours is shown in the chosen translation (translate.inc), at most 39 bytes as the label holds.
        if (site->kind == L_TRYBABY) { if (c.n > 0) src = TrA(c.v[0], 39); }
        else if (c.n > 0) { int r = LabelRandom(c.n + 1); if (r) src = TrA(c.v[r - 1], 39); }
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
