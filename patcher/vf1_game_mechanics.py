"""Game Mechanics: how Virtual Families works underneath, from the stock game's own code (the Tools tab's window).

The model is the Virtual Villagers Fun Patcher's Game Mechanics window: the rules are grouped (GROUPS), every
line is a bullet with its evidence label right beside it, and every time names its clock (CLOCKS below).  It is
for the curious and it only reads: it opens no save, game file or install, and writes nothing.

CLOCKS.  Every duration, rate and timer says "real time" or "game time" (or counts in age units), read from the
routine that times it (docs/game-mechanics/timer_sites.tsv lists every clock call):
  real time  the wall clock: GetSecondsFromGameStart 0x4036D0 (time() less the save's start, which the save keeps,
             so it also counts while the game is closed) or ldwEventManager::GetSeconds 0x401F20 (time() itself),
             or the PC's clock for day and night.  Neither reads the speed or the pause.
  game time  CGameTime::Seconds 0x422320 = banked + real seconds since its mark / (speed / 10); paused it returns the
             banked value.  It is saved with its mark (0x4222C0) and loaded with it (0x4223F0, from the load at
             0x424B53), so on loading it counts on over the time the game was closed, at the saved speed, with no
             limit (the patcher always saves at Normal).
  age units  each family member's own bank of real seconds divided by 60 x speed (0x489D00): 600 game seconds at
             every speed; the bank is emptied while paused and a closed game's gap is cut to the time-away limits.

EVIDENCE.  Every line carries one label, always shown (docs/game-mechanics/spec.md, "Evidence labels"):
  VERIFIED-E   the game's own routine was run as linked (in an emulator) with the inputs the game supplies, and
               its odds counted over every value of the game's random number;
  VERIFIED-C   the rule is the game's own instruction sequence, on a call path traced from the running game;
  UNCONFIRMED  anything else: not on a traced path, reached only from player input that was not traced, a
               meaning the code does not show, or the patcher's own features read from its source.
Nothing is inferred from save values, and code that is in the exe but not shown to run is never presented as
something the player can do: the few such lines (Hidden keys, clicks and cheats) start "DEAD (never runs)" and say
why nothing reaches them.

UNPATCHED AND PATCHED.  The page describes the game without the patcher.  Wherever the Fun Patcher changes what a
line says, a line starting "With the patcher" follows it, naming the patch setting (manifest.json label) and
whether it is on by default (PATCH_SETTINGS; the test checks both against manifest.json).  Where the two are the same
nothing is added.  Those lines were verified with the patcher's own vf1fun.dll (and vf1kids.dll), built from
native/ and mapped beside the vanilla exe in the same unicorn harness: its VF1Fun_Startup ran first with the
manifest defaults, so every hook it installs was in the emulated image as it writes it, then the game's routines
(and the DLL's per-frame VF1Fun_Tick) ran with the inputs the game supplies (docs/game-mechanics/spec.md section 22).

SPEEDS.  VF1's speed value is a divisor (10 = Normal, the only speed the stock game sets).  One age unit takes
60 x speed real seconds and a game second takes speed / 10 real seconds.  The patcher's Time Controls patch adds
Slow (20) and Fast (5), and 5x (2) and 10x (1); it always saves a family at Normal (or Paused) and loads any other
saved speed as Normal, so the time a closed game catches up on is always counted at Normal.  Times are written
for Normal with Slow and Fast beside them.  Paused (the speed plus 999) stops the game clock (spec commit
db2d45a: CGameTime::SetSpeed stores speed 0 and Seconds() returns the banked value).  An age unit is 10 game
minutes; a game second takes 2 / 1 / 0.5 / 0.2 / 0.1 real seconds at Slow / Normal / Fast / 5x / 10x.

The owner's four decisions were each re-checked in the stock exe before going in (Game Mechanics branch,
2026-10-25); only what held is shown:
  * Interest has no cap on missed game days: shown (UpdateInterest 0x422830 emulated for 1..100 days, called every
    3 age units from the happiness update 0x48FFB2 <- upkeep 0x48BD57 <- 0x424F93 <- UpdateScene 0x444E9A).
  * Malfunctions roll while paused: shown (the 2-second step 0x444E28..0x444FEC run at speed 1009 rolls
    rand(800) and calls SetProp 0x4938C0; GameUpdate 0x422D90 and Run 0x402CC0 call the scene with no pause test).
  * The hidden fifth food-group slot: shown in its accurate form, not as proposed.  FoodGroupsActive 0x48FE30
    counts the extra group for a family member without a career only while the low byte of the Grains slot's
    expiry is non-zero: one with only Dairy counts 1, not 2, and one whose Grains ran out still counts 1 with no
    group at all.  So the rule shown is "once they have had Grains", not "any food group" (EXTRA_GROUP).  Old age
    at 61 with 4 groups: 10.01% without a career, 20.02% with one; sickness with 4 groups and no career: 0.504%.
    The tables stay for family members with a career, who count each active group once.
  * The health floor ("starvation and disease cannot kill"): NOT shown.  The per-unit Starvation and Disease
    losses are 1 point and stop at 14, but the 3-unit health check takes 2 points at hunger 100 (1 below 15):
    emulated, a starving family member at 14 health with every per-unit starvation roll missed reaches 0 in
    90 age units, recorded as Unknown causes.  That is shown instead.

VIRTUAL FAMILIES 2 PARITY (owner, 2026-10-27: "Vf1 should also get the same stuff as vf2!!!").  The groups of the VF2
page (src/vf2_game_mechanics.py, main af2cc46) are all here: Weather, Dropping a family member on things, Pets,
Clothing and Hairstyles, Trophies and the heir and Actions are new, and Careers, Pregnancy and babies, Old age and
death, Random Events and Collectibles go as deep.  Where VF2 has a mechanic this game lacks, one line says
"not in Virtual Families 1" (NOT_IN_VF1).  Every number was read or run in VF1's own exe (per-function disassembly,
unicorn runs of the drop-table and collectible constructors, every action's code paths, every reached call of the
trophy counter); only two lines stay UNCONFIRMED, and each says why (only a live game run shows it).  The store's
six random items are the Flea Market, the owner's name; the code's "specials" is named once, in Store rules.

`python vf1_game_mechanics.py` prints the whole page, for review.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

TITLE = "Game Mechanics"

VERIFIED_E, VERIFIED_C, UNCONFIRMED = "VERIFIED-E", "VERIFIED-C", "UNCONFIRMED"
LABELS = (VERIFIED_E, VERIFIED_C, UNCONFIRMED)

INTRO = ("For the curious: how Virtual Families works underneath, worked out from the game's own code. Every time "
         "says which clock it runs on, real time or game time (see Clocks). It only reads: no save or game file is "
         "opened or changed, so the game may be running.")
CLOCK_NOTE = ("Clocks. Real time is the wall clock (your PC's clock): it runs the same at every game speed, while the "
              "game is paused and while it is closed. Game time is the game's own clock: it runs with the game speed "
              "(1 game second is 1 real second on Normal, 2 on Slow, 0.5 on Fast, 0.2 at 5x and 0.1 at 10x), stops "
              "while paused, and while the game is closed runs on at Normal with no limit (a family "
              "saved paused stays stopped). Ages count in age units: 1 age unit is 10 minutes of game time (10 minutes "
              "real time on Normal) and 20 age units are 1 year (3 hours 20 minutes real time on Normal). Ageing "
              "stops while paused, and the time the game is closed is caught up only within the time-away limits "
              "(see Time and ageing).")
PATCHER_PREFIX = "With the patcher"
PATCHER_NOTE = ("This page describes the game without the patcher. Wherever the Fun Patcher changes something, the "
                "line after it starts \"With the patcher\", names the patch setting that does it and says whether "
                "that setting is on by default.")
LABEL_NOTE = ("Every line says what stands behind it. VERIFIED-E: the game's own code was run with the values the "
              "game gives it, and the chances counted exactly. VERIFIED-C: read in the game's own code, on a path the "
              "running game is shown to take. UNCONFIRMED: not yet shown either way. For a \"With the patcher\" "
              "line the patcher's own code was run or read together with the game's in the same way. A line starting "
              "\"DEAD (never runs)\" is code left in the game that nothing ever reaches: it says why, and it is not "
              "something you can do.")
SPEED_NOTE = ("A game-time length is shown with the real time it takes on Normal, the only speed the stock game has, "
              "and on Slow and Fast, the patcher's Time Controls speeds (Slow is half speed, Fast double; at its 5x "
              "and 10x a game-time length takes 0.2 and 0.1 times its Normal real time). Chances are the game's exact odds: its random "
              "numbers make \"less than 30 in 100\" 30.03%, not 30%.")

# The patch settings the page names (patcher/manifest.json: id -> the label the patcher shows, on by default).
PATCH_SETTINGS = {
    "OlderVillagerMortalityCurve": ("Older Villager Mortality Curve", True),
    "PrivateRomanticTime": ("Private Adult Romantic Time", True),
    "UpTo28Children": ("Up to 28 Children", False),
    "AllowOlderPregnancies": ("Allow Older Pregnancies", True),
    "ClampMoneyAndFood": ("Clamp Max Money and Food", True),
    "SpecialUpgrades": ("Add visible mobile version purchases", True),
    "CheatUpgrades": ("Cheat Upgrades", True),
    "RollTheDice": ("Roll the Dice", True),
    "FixVanillaGameBugs": ("Fix Vanilla Game Bugs", True),
    "FleaMarket": ("Flea Market", True),
    "StoreRefreshKey": ("R Refreshes the Store", True),
    "RenderUnicodeInGameFonts": ("Render Unicode with In-Game Fonts", True),
}
# The Upgrades menu's own page titles, as the patcher shows them (named on the page as they appear).
UPGRADES_PAGES = ("Cheat Upgrades", "Villager Cheats", "Store, Achievement and Collection Cheats", "House and Yard",
                  "Time Controls", "Special Upgrades", "Family: Marriage, Babies and Adoption", "Flea Market",
                  "Roll the Dice", "Patcher Achievements", "Clothing and Hairstyles")


def setting(key: str) -> str:
    """'Allow Older Pregnancies, on by default': a setting as a "With the patcher" line names it."""
    label, on = PATCH_SETTINGS[key]
    return f"{label}, {'on' if on else 'off'} by default"


def with_patcher(key: str, text: str) -> str:
    """'With the patcher (Allow Older Pregnancies, on by default): ...'."""
    return f"{PATCHER_PREFIX} ({setting(key)}): {text}"


# A Special Upgrade, bought per family on the Upgrades menu's Special Upgrades page.
def upgrade(name: str, price: str, text: str) -> str:
    return (f"{PATCHER_PREFIX}'s {name} (a Special Upgrade, {price}, bought for the family; "
            f"{setting('SpecialUpgrades')}): {text}")

BULLET, SUB_BULLET = "\u2022 ", "    \u2013 "   # escapes, so no re-encoding of this file can garble them

# The game's speed values: real seconds per 10 game seconds; one age unit = 60 x speed real seconds.
SLOW, NORMAL, FAST = 20, 10, 5
PAUSED = 999
AGE_UNIT_SECONDS = 60          # x the speed value
YEAR_UNITS = 20

KEYS = "Hidden keys, clicks and cheats"
TIME = "Time and ageing"
NEEDS = "Needs and upkeep"
HEALTH = "Health"
SICKNESS = "Sickness"
OLD_AGE = "Old age and death"
BABIES = "Pregnancy and babies"
CAREERS = "Careers and promotion"
MONEY = "Money and interest"
LEAVING = "Leaving home"
MARRIAGE = "Dating, marriage and the next generation"
EVENTS = "Random Events"
WEATHER = "Weather"
MESSES = "Messes"
COLLECTIBLES = "Collectibles"
MALFUNCTIONS = "Malfunctions"
STORE = "Store rules"
STORE_FOOD = "Store: groceries"
STORE_MEDS = "Store: medicines"
STORE_SPECIALS = "Store: Flea Market"
STORE_OTHER = "Store: other items"
HOME = "Home Improvements"
CAREER_ROOMS = "Career Room Upgrades"
DROPS = "Dropping a family member on things"
PETS = "Pets"
CLOTHING = "Clothing and Hairstyles"
TROPHIES = "Trophies and the heir"
ACTIONS = "Actions"
PATCHER_SPECIAL = "Patcher: Special Upgrades"
PATCHER_MENU = "Patcher: Upgrades menu"
INDEX = "Chance and timer index"
GROUPS = (KEYS, TIME, NEEDS, HEALTH, SICKNESS, OLD_AGE, BABIES, CAREERS, MONEY, LEAVING, MARRIAGE, EVENTS, WEATHER,
          MESSES, COLLECTIBLES, MALFUNCTIONS, STORE, STORE_FOOD, STORE_MEDS, STORE_SPECIALS, STORE_OTHER, HOME,
          CAREER_ROOMS, DROPS, PETS, CLOTHING, TROPHIES, ACTIONS, PATCHER_SPECIAL, PATCHER_MENU, INDEX)
# Where Virtual Families 2 has a mechanic this game does not, the page says so in one line ending with these words.
NOT_IN_VF1 = "not in Virtual Families 1"
# "Flea Market" is the owner's name for the store's six random items; the game's code calls them the specials (said
# once on the page, in Store rules). The patcher's own Upgrades-menu page of the same name is always called "the
# patcher's Flea Market page (Upgrades menu)".


@dataclass(frozen=True)
class Fact:
    """One line of the page: a bullet under its group (`sub`: an indented dash under the line before it), with
    its evidence label (LABELS) shown beside it."""
    group: str
    text: str
    label: str
    sub: bool = False

    def __post_init__(self) -> None:
        if self.group not in GROUPS:
            raise ValueError(f"unknown group {self.group!r}")
        if self.label not in LABELS:
            raise ValueError(f"unknown label {self.label!r}")


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def duration(seconds: float) -> str:
    """A real length of time in words, to the second: "3 hours 20 minutes", "1 hour 45 minutes", "90 seconds"
    is "1 minute 30 seconds"."""
    seconds = int(round(seconds))
    if seconds < 60:
        return _plural(seconds, "second")
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [_plural(n, unit) for n, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")) if n]
    return " ".join(parts)


def unit_seconds(units: float, speed: int) -> float:
    """Real seconds that `units` age units take at `speed`."""
    return units * AGE_UNIT_SECONDS * speed


def game_seconds(game: float, speed: int) -> float:
    """Real seconds that `game` game seconds take at `speed`."""
    return game * speed / NORMAL


def at_speeds(real_at: object) -> str:
    """'X real time on Normal, Y on Slow, Z on Fast' for a function of the speed giving real seconds."""
    return (f"{duration(real_at(NORMAL))} real time on Normal, {duration(real_at(SLOW))} on Slow, "
            f"{duration(real_at(FAST))} on Fast")


def game_text(game: float) -> str:
    """'1 hour of game time: 1 hour real time on Normal, 2 hours on Slow, 30 minutes on Fast' -- a length on the
    game's own clock with what it takes in real time at each speed (for use inside brackets)."""
    return f"{duration(game)} of game time: " + at_speeds(lambda speed: game_seconds(game, speed))


def game_span(game: float) -> str:
    """'1 hour of game time (1 hour real time on Normal, 2 hours on Slow, 30 minutes on Fast)' (in a sentence)."""
    return f"{duration(game)} of game time (" + at_speeds(lambda speed: game_seconds(game, speed)) + ")"


# One age unit is 60 x speed real seconds, and a game second speed / 10 real seconds, so an age unit is 600 game
# seconds (10 game minutes) at every speed.
AGE_UNIT_GAME_SECONDS = AGE_UNIT_SECONDS * NORMAL


def game_range(low: float, high: float) -> str:
    """'6 minutes 32 seconds to 12 minutes 31 seconds real time on Normal, ... on Slow, ... on Fast'."""
    return ", ".join(f"{duration(game_seconds(low, s))} to {duration(game_seconds(high, s))}"
                     + (" real time on Normal" if s == NORMAL else f" on {name}")
                     for s, name in ((NORMAL, "Normal"), (SLOW, "Slow"), (FAST, "Fast")))


def units_text(units: float) -> str:
    """The game time `units` age units take, with its real time at each speed (for use inside brackets)."""
    return game_text(units * AGE_UNIT_GAME_SECONDS)


def units_span(units: float) -> str:
    return game_span(units * AGE_UNIT_GAME_SECONDS)


# ---------------------------------------------------------------------------
# The careers (docs/game-mechanics/careers.tsv: CVillagerSkills::Reset 0x48EFF0 picks rand(108); names are
# string 0x112 + id; CareerType 0x48F080; the eight level salaries from the table at 0x4FCFF8)
# ---------------------------------------------------------------------------

LEVELS = ("Beginner", "Novice", "Apprentice", "Licensed", "Practiced", "Accomplished", "Exceptional", "Master")
_CAREERS = """\
1|Pastry Designer|30,35,43,48,56,65,78,100
1|Wine Critic|20,25,30,38,48,60,75,95
1|BBQ Sauce Creator|5,10,18,36,58,90,150,230
1|Food Critic|20,25,30,38,48,60,75,95
1|Cocktail Inventor|14,18,22,30,35,42,80,110
1|Soup Taster|15,18,22,27,33,40,50,70
1|Caterer|30,35,43,48,56,65,78,100
1|Cake Designer|30,35,43,48,56,65,78,100
1|Mustard Bottler|20,25,30,38,48,60,75,95
1|Coffee Blender|20,25,30,38,48,60,75,95
1|Personal Cook|35,45,58,68,80,94,115,140
1|Fresh Pasta Maker|20,25,30,38,48,60,75,95
1|Doughnut Decorator|20,25,30,38,48,60,75,95
1|Candy Designer|30,35,43,48,56,65,78,100
1|Food Photographer|30,35,43,48,56,65,78,100
1|Fruit Examiner|20,25,30,38,48,60,75,95
1|Salad Packager|15,18,22,27,33,40,50,70
1|Meat Grader|30,35,43,48,56,65,78,100
1|Mail-order Butcher|20,25,30,38,48,60,75,95
1|Nut Processor|15,18,22,27,33,40,50,70
1|Dry Fruit Packager|20,25,30,38,48,60,75,95
1|Mail-order Baker|20,25,30,38,48,60,75,95
1|Soup Inventor|20,25,30,38,48,60,75,95
1|Recipe Inventor|5,10,18,36,58,90,150,230
1|Vitamin Inventor|5,10,18,36,58,90,150,230
1|Pesto Sauce Creator|5,10,18,36,58,90,150,230
1|Ketchup Bottler|15,18,22,27,33,40,50,70
1|Trail Mix Creator|20,25,30,38,48,60,75,95
1|Chewing Gum Designer|5,10,18,36,58,90,150,230
1|Spice Mixer|30,35,43,48,56,65,78,100
2|Engineer|30,35,43,48,56,65,78,100
2|Architect|30,35,43,48,56,65,78,100
2|Domain Name Seller|15,20,25,32,40,55,70,90
2|Video Game Designer|5,10,18,36,58,90,150,230
2|Tech Consultant|15,20,25,32,40,55,70,90
2|Hacker|15,20,25,32,40,55,70,90
2|Fiction Writer|20,25,30,38,48,60,75,130
2|Journalist|15,20,25,32,40,55,70,90
2|Lawyer|30,35,43,48,56,65,78,100
2|Screenplay Writer|12,18,22,27,53,80,150,170
2|Envelope Stuffer|15,18,22,27,33,40,50,70
2|Graphic Designer|30,35,43,48,56,65,78,100
2|Day Trader|35,20,28,55,40,32,170,80
2|Poet|15,18,22,27,33,40,120,170
2|Lyricist|15,20,25,32,40,55,70,90
2|Programmer|35,45,58,68,80,94,115,140
2|Accountant|20,25,30,38,48,60,75,95
2|Publicist|15,20,25,32,40,55,70,90
2|Nonfiction Writer|12,15,19,24,29,55,75,130
2|Fairy Tale Writer|20,25,30,38,48,60,75,95
2|Translator|30,35,43,48,56,65,78,100
2|QA Engineer|30,35,43,48,56,65,78,100
2|Telemarketer|18,22,25,32,40,55,70,80
2|Talent Agent|5,10,18,36,58,90,150,230
2|Recruiter|30,35,43,48,56,65,78,100
2|Video Game Reviewer|20,25,30,38,48,60,75,95
2|Essay Writer|15,18,22,27,33,40,50,70
2|Web Designer|30,35,43,48,56,65,78,100
2|Art Critic|20,25,30,38,48,60,75,95
2|Music Critic|20,25,30,38,48,60,75,95
2|Book Reviewer|20,25,30,38,48,60,75,95
2|Online Gold Farmer|15,18,22,27,33,40,50,70
2|Marketing Agent|30,35,43,48,56,65,78,100
2|Paralegal|20,25,30,38,48,60,75,95
2|Census Taker|15,18,22,27,33,40,50,70
2|Digital Photo Editor|20,25,30,38,48,60,75,95
2|Magazine Editor|20,25,30,38,48,60,75,95
2|Rocket Scientist|30,35,43,48,56,65,78,100
2|Lobbyist|35,45,58,68,80,94,115,140
2|Math Tutor|15,18,22,27,33,40,50,70
2|History Tutor|15,18,22,27,33,40,50,70
2|English Tutor|15,18,22,27,33,40,50,70
2|Statistician|20,25,30,38,48,60,75,95
2|Online Store Operator|5,10,18,36,58,90,150,230
2|Travel Writer|20,25,30,38,48,60,75,95
2|Technical Writer|30,35,43,48,56,65,78,100
2|Sustainability Consultant|30,35,43,48,56,65,78,100
2|Artist|20,25,30,38,48,60,75,95
2|Spammer|20,25,30,38,48,60,75,95
3|Wood Sculptor|20,25,30,38,48,60,75,130
3|Dress Maker|20,25,30,38,48,60,75,95
3|Toaster Repairer|15,18,22,27,33,40,50,70
3|Dress Designer|35,45,58,68,80,94,115,140
3|Candle Maker|30,35,43,48,56,65,78,100
3|Jewelry Maker|5,10,18,36,58,90,150,230
3|Film Processor|15,18,22,27,33,40,50,70
3|Inventor|15,20,25,32,40,55,70,90
3|Board Game Designer|30,35,43,48,56,65,78,100
3|Model Builder|20,25,30,38,48,60,75,95
3|Basket Maker|15,20,25,32,40,55,70,90
3|Knife Sharpener|15,18,22,27,33,40,50,70
3|Glue Mixer|15,18,22,27,33,40,50,70
3|Silverware Polisher|20,25,30,38,48,60,75,95
3|Tool Maker|20,25,30,38,48,60,75,95
3|Toy Maker|20,25,30,38,48,60,75,95
3|Box Maker|15,18,22,27,33,40,50,70
3|Shoe Maker|5,10,18,36,58,90,150,230
3|Dental Tool Maker|35,45,58,68,80,94,115,140
3|Lens Crafter|30,35,43,48,56,65,78,100
3|Key Maker|15,18,22,27,33,40,50,70
3|Picture Framer|20,25,30,38,48,60,75,95
3|Soap Inventor|5,10,18,36,58,90,150,230
3|Eyeglass Repairer|30,35,43,48,56,65,78,100
3|Ceramics Designer|20,25,30,38,48,60,75,95
3|Denture Maker|20,25,30,38,48,60,75,95
3|Camera Repairer|30,35,43,48,56,65,78,100
3|Watch Fixer|30,35,43,48,56,65,78,100
3|Pen Designer|5,10,18,36,58,90,150,230
"""


@dataclass(frozen=True)
class Career:
    id: int
    room: int                       # CareerType 1..3: which career room it uses
    name: str
    salaries: tuple[int, ...]       # by level, Beginner .. Master


CAREER_LIST: tuple[Career, ...] = tuple(
    Career(i, int(room), name, tuple(int(s) for s in pay.split(",")))
    for i, (room, name, pay) in enumerate(line.split("|") for line in _CAREERS.splitlines() if line))


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

# Hidden keys, clicks and cheats (research 2026-10-27, C:\vf1\gm_research t_keys.py / keymap.py / cmap.py):
# The engine's event pump 0x4047B0 (ldwGame::Run 0x402CC0 -> 0x40A0D0 -> 0x4092D0, every frame) polls SDL and posts
# through ldwEventManager 0x401E80 to every active scene (ldwScene::SetActive 0x40C700 registers it):
#   SDL_TEXTINPUT, one byte  -> (5, 0, the typed character)      0x4049C4  (so 'r' and 'R' differ)
#   SDL_KEYDOWN Backspace    -> (5, 8, 8)                        0x40494A
#   SDL_KEYDOWN Esc 1000, Tab 1002, Enter 1003, Delete 1013, Left 1004, Right 1005, Up 1006, Down 1007, PageUp 1008,
#     PageDown 1009, Home 1010, End 1011, Insert 1012, F1 1018 .. F10 1027 -> (6, id, key)   tables 0x404ADC/0x404B54
#   Alt+F4 (mod & 0x300)     -> quit, as closing the window      0x4048A8
#   mouse move/down/up       -> (1/2/3, x, y), left button only  0x4049DE; the wheel and other buttons are dropped
# Scene key handlers (vtable slot 2, HandleEvent(type, a, b)): store 0x4499D0 ('M'/'m'/Esc leave, 'r' redraw),
# house 0x440E00 -> chars 0x440B40 (table 0x440D78), keys 0x440DD0 (Esc); Achievements/Adoption/Dating/Family tree
# share 0x439150 (Esc = command 1: Back / Adopt / Marry / Back); Collection 0x437330 (Esc, F1); Details 0x44B990
# (Esc = its back button, 1); Help 0x440260 (F1 -> house); splash 0x4488A0 (any char: next logo; F1 -> house);
# dialogs 0x41CE50 (Enter = 1, Esc = 2), Bank 0x4152A0 / Change Player 0x41B5C0 / Diagnosis 0x416C70 (both = 1).
# The store's 'r': 0x4499EA cmp 0x72 -> 0x496DB0 (allowed unless the specials' due time, store+0x13C, is 3 to 4 real
# hours away: i.e. more than 3,600 real s since the draw), then the specials draw 0x449480(-1), the outfit pictures
# 0x496C70(1) and the labels 0x449100; emulated in t_keys.py (3,600 s: nothing; 3,601 s: redrawn; 'R': nothing).
# Clicks: the house's click 0x4415C0 (on mouse down, nobody under it) switches on the content-map object id
# (Assets\cmap.dat bits 18..24; table 0x441ACC); the random-tip spot 0x44718C (rect +0x88..+0x94 = 171,488..221,584,
# reached only outside the view 0,0..800,561) shows tip rand(50); the loading screen's ctor 0x440450 shows rand(30).
# The TV remote: gs+0x17C in place, +0x178 the real hour it goes missing, +0x180/+0x184 where it lies (0x423A90
# return, 0x423AE0 lose, 0x424460 the 2-second check, 0x4428A0/0x4429C0 the drop and the carry). The shed door:
# gs+0x168 (0 needs fixing, 1 being fixed, 2 fixed), +0x16C open for good (0x4890B6, achievement 0x3C).
# Dead: scene 5 (theAlignVillagerScene, with CAlignAnimScene/CEditAnimScene) is built by the loader 0x423211 but no
# code ever sets gs+0x1B300 = 5; CLightSourceEditor (keys 0x44DB30) and CWaypointEditor (keys 0x44DED0) are static
# objects at 0x56B070 / 0x56B08C built by the CRT initializers 0x4B17B0 / 0x4B17C0 (table 0x4B24E0), and nothing else
# in the exe refers to either object or to their vtables, so no key ever reaches them; the house's typed F-W-K/R
# state (scene +0x50) is written and never read.
RANDOM_TIPS = (
    "If you praise every behavior, how will your family members know what to do?",
    "If you punish too many behaviors, your family members can get depressed.",
    "Your virtual friends have minds of their own.",
    "All work and no play makes Jack a dull boy.",
    "It can be hard to live alone.",
    "The house and its improvements are passed through generations.",
    "Your new friend will be happiest with a compatible spouse.",
    "Two people who work in the same room can share resources.",
    "Not all jobs are equal.",
    "Different careers have different pay curves.",
    "Life is full of drama.",
    "Money can't buy happiness... well, maybe it can buy a little.",
    "Your little friends sometimes leave appliances running.",
    "It's nice to repair the house for future generations.",
    "An untidy house can wear down anyone's cheer eventually.",
    "The weeds in the yard are relentless!",
    "Different illnesses require different treatments.",
    "Your virtual family is in the same time zone as you are.",
    "Your little friends appreciate affection from you.",
    "Couples who want children won't be as happy without them.",
    "Couples who do not want children may still have them.",
    "Couples differ in their ability to have children.",
    "Gently selecting peeps doesn't disrupt what they're doing.",
    "You live, and you learn.",
    "If your virtual friends are very sad, make sure they have food.",
    "Professional advancement can be a great joy in life.",
    "A large family can be a great source of joy... and loose socks.",
    "They do not like the red glove at all.",
    "Children tend to move out at a certain age.",
    "It's nice to stay indoors when it rains.",
    "If your hand gets tired, give it a rest!",
    "Praising a behavior reinforces it.",
    "Who made this house?",
    "Your working friends get paid hourly, too.",
    "Save or spend? Gain bank interest or get shiny new stuff?",
    "You can encourage meals and discourage snacking.",
    "There is more to life than just making money.",
    "Learn from yesterday, live for today, hope for tomorrow.",
    "If someone is sick a lot, consult a doctor.",
    "Happiness is a choice that requires effort at times.",
    "Medical treatment is expensive.",
    "It's never too late to have a happy childhood.",
    "Random events can be good or bad.",
    "It's good to wait for your perfect match... but for how long?",
    "The ability to make children slowly decreases with age.",
    "Marriage proposals come less frequently with age.",
    "Older family members start to slow down.",
    "Older family members change their idea of what is fun.",
    "Kids can swim!",
    "Collecting bugs? Try when it rains...",
)


# What queues each tutorial tip (the tip window's queue 0x44E180, or the tutorial check 0x44E2D0 in UpdateScene), from
# every reached instruction that pushes the tip's text number 0x4D8..0x4FE (research 2026-10-27, p_tips.py).
TUTORIAL_TIPS = (
    "“Welcome to Virtual Families! ...”: the house screen, when a new family's first family member is "
    "home.",
    "“Good! This is how you move about the house. ...”: the house screen, once the view has been dragged.",
    "“Perfect! A white circle highlights your little friend. ...”: clicking a family member.",
    "“Excellent! Moving people is just that easy.”: the house screen, once a family member has been "
    "dragged.",
    "“Well done. Dragging someone to the bathroom sink ...”: dropping a family member on a bathroom sink.",
    "“Good. The wrapper is being discarded. ...”: the action Throwing away a wrapper starting.",
    "“Nice job! They really appreciate having enough to eat.”: a grocery bag dropped in the kitchen.",
    "“Wonderful! They know that you like this behavior, ...”: praising with the green glove.",
    "“Great! Your adoptee earned his first money ...”: a successful piece of career work.",
    "“Good! Let's give the little person a moment to finish a work cycle. ...”: a Working on career "
    "action starting.",
    "“Oops! That little puff of smoke means that the work didn't go well. ...”: a piece of career work "
    "failing.",
    "“Good! They are going to have ...”: Trying to make a baby starting.",
    "“Too bad! They aren't in the mood. ...”: a try for a baby refused (see Pregnancy and babies).",
    "“Hmmm... this little person is confused. ...”: the action Confused starting.",
    "“You have mastered the basics! ...”: the house screen, after the tutorial's last step.",
    "Set up by number in the tutorial's start-up list: the adoption tip, the white-circle tip and the "
    "instructions for the bathroom sink, the groceries, the praise glove, the Detail button, the career and the "
    "Store button.",
    "No code queues these (every instruction the game runs was searched; for the first two the code only asks "
    "whether they have been shown): “Let's start with the basics. ...”, “Let's move your little "
    "friend. ...”, “Let's get to know your little friend. ...”, “Hmm, the house seems pretty "
    "messy. ...”, “You have email! ...”, “How exciting - a new marriage! ...”, "
    "“Almost! Click and hold ...”, “Ooh! The stork brought a baby. ...”, “Virtual "
    "Families is a true real-time simulation game. ...”, “Nice try, but children don't work. ...” "
    "and “Nursing mothers don't work at their careers ...”.",
)


def _below(n: int, k: int) -> int:
    """How many of rand()'s 32,768 values give GetRandom(n) = rand() % n below k."""
    k = max(0, min(k, n))
    full, rest = divmod(32768, n)
    return full * k + min(k, rest)


def _pct(hits: int) -> str:
    return f"{100 * hits / 32768:.2f}%"


def _below_pct(n: int, k: int, invert: bool = False) -> str:
    hits = _below(n, k)
    return _pct(32768 - hits if invert else hits)


def _agree(w1: int, w2: int) -> str:
    """The meeting's agreement roll (0x48724B): GetRandom(105) <= 10 x (10 - w1 / 20 - w2 / 20)."""
    return _below_pct(105, 10 * (10 - w1 // 20 - w2 // 20) + 1)


def _twins(bonuses) -> list[tuple[int, str, str, str]]:
    """Impregnate 0x4864D0: twins or more if GetRandom(100) < 7 + B, then triplets if GetRandom(100) < 25 + B."""
    out = []
    for b in bonuses:
        more = _below(100, 7 + b) / 32768
        tri = more * _below(100, 25 + b) / 32768
        out.append((b, f"{100 * (1 - more):.2f}%", f"{100 * (more - tri):.2f}%", f"{100 * tri:.2f}%"))
    return out


def _odds(k: int, n: int) -> str:
    """GetRandom(n) = rand() % n landing on k: '2.002%' (rand()'s 32,768 values counted)."""
    hits = 32768 // n + (1 if k < 32768 % n else 0)
    return f"{100 * hits / 32768:.3f}%"


def _keys() -> list[Fact]:
    g, E, C, U = KEYS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    tips = [Fact(g, f"Tips {n + 1} to {n + 5}: " + " ".join(f"{n + 1 + k}. \u201c{t}\u201d"
                                                             for k, t in enumerate(RANDOM_TIPS[n:n + 5])), C, sub=True)
            for n in range(0, len(RANDOM_TIPS), 5)]
    return [
        Fact(g, "How the game reads the keyboard: a letter, digit, space or other character reaches it as the "
                "character you type, so Shift and Caps Lock matter (a small r and a capital R are different keys "
                "to it) and on any keyboard layout it is the key that types that character. Esc, Enter, F1 and "
                "Alt+F4 reach it as keys. Tab, the arrow keys, Insert, Delete, Home, End, Page Up, Page Down and F2 "
                "to F10 are passed on but nothing in the game uses them, Backspace only edits a name box, and no "
                "Ctrl, Shift or Alt combination does anything (Alt+F4 quits, the same as closing the window). Only "
                "the left mouse button counts: the right and middle buttons and the wheel are ignored.", C),
        Fact(g, "The store's hidden key: typing a small r while the store page is open (the R key without Shift "
                "and with Caps Lock off; a capital R does nothing) redraws all six Flea Market items at once, for free, and "
                "also draws new Male Outfit and Female Outfit pictures. It works only when more than 1 hour of real "
                "time has passed since the Flea Market was last drawn (checked: exactly 1 hour after a draw nothing "
                "happens; 1 hour and 1 second after, they are redrawn); otherwise the key does nothing. Each redraw "
                "starts the Flea Market's wait again, so the next automatic change comes 4 hours of real time after the "
                "key, and the key works again after 1 more hour of real time: at most once an hour of real time, "
                "at any game speed, also while paused.", E),
        Fact(g, "What the redraw does not change: the half-price grocery (checked), and it takes no money. The "
                "new Flea Market items follow the same rules as the automatic draw (see Store: Flea Market); the outfit "
                f"pictures' own wait starts again too ({game_text(14_400)}).", E, sub=True),
        Fact(g, with_patcher("FixVanillaGameBugs", "the R key's redraw is the same draw as the automatic one, so a "
                                                   "family with a dog is offered the Pet Turtle there too, and each "
                                                   "outfit already bought keeps its own picture."), C, sub=True),
        Fact(g, with_patcher("StoreRefreshKey", "a patcher key: R, small or capital, on the store page redraws the "
                             "Flea Market (the store's six random items) "
                             "and both outfit pictures every time it is pressed, with no 1-hour wait. It is the stock "
                             "key's own redraw, so the items and pictures follow the same draw and odds, and the next "
                             "automatic draw comes 4 hours of real time later, as after the stock key (checked: r and "
                             "R at once, again and again). The half-price grocery, its price and its wait never "
                             "change, nothing is paid, and outfits already bought keep their pictures (checked). R "
                             "does nothing on any other screen, and nothing on the patcher's Flea Market page (Upgrades menu), "
                             "which lists every tray item at once and has nothing to redraw."), E, sub=True),
        Fact(g, "M (either case) or Esc on the store page goes back to the house.", C, sub=True),
        Fact(g, "Every part of the store was checked for other keys: the store is one screen (the Flea Market, the "
                "groceries with the half-price grocery, the medicines, the outfits, the Home Improvements and the "
                "career room upgrades are all on it), and its only key handler takes the small r, M and Esc. No key "
                "changes the half-price grocery, the Home Improvements or the career room upgrades, and only the r "
                "key redraws the outfit pictures. The buy and message dialogs over it take only Enter and Esc (see "
                "Dialogs below).", C, sub=True),
        Fact(g, "In the house: Space pauses and unpauses (see Time and ageing).", C),
        Fact(g, "In the house, typed letters (either case) are shortcuts for the buttons along the bottom: S the "
                "Store, D the Details screen (of the family member selected, or the one selected last, or the first "
                "one; with nobody at home it does nothing), F the Family screen, C the Collections screen, T the "
                "Trophies screen; Esc goes to the main menu.", C),
        Fact(g, "In the house, the number keys 1 to 9 (the top row, or the number pad with Num Lock on) jump the "
                "view to nine fixed places laid out like the number pad: 7, 8 and 9 along the back of the yard, "
                "4, 5 and 6 across the middle of the house, 1, 2 and 3 along the front yard; left, middle and "
                "right.", C),
        Fact(g, "In the house, K (either case) or a capital R loses the TV remote at once: it is put down again at a "
                "random spot (see The TV remote below). A small r does nothing in the house. M, P, the apostrophe, "
                "the semicolon and the square brackets are taken but do nothing.", C),
        Fact(g, "DEAD (never runs): the house also notes typing F, then W, then K or R, but nothing ever reads it; "
                "and F leaves the house for the Family screen anyway. So the sequence does nothing beyond what each "
                "key does on its own.", C, sub=True),
        Fact(g, "Esc on the Adoption screen is the Adopt button: it adopts the child shown, with the name typed in "
                "the box (the child's own name if the box is empty), exactly as clicking Adopt.", C),
        Fact(g, "Esc on the marriage proposal screen (Virtual Families Matchmaking) is the Marry button: it accepts "
                "the proposal, exactly as clicking Marry. To turn a proposal down, click Reject.", C),
        Fact(g, "Esc on the Trophies and Family screens goes back to the house; on the Collections screen Esc and "
                "F1 both do; on the Details screen Esc is its back button and keeps a name typed into its name "
                "box. On the Help screen F1 goes straight to the house (its own button goes back to the main "
                "menu).", C),
        Fact(g, "Dialogs: Enter is the dialog's command 1 and Esc its command 2 in the message, purchase, family "
                "tree name and nickname dialogs; in the Bank, Change Player and the doctor's diagnosis dialogs Enter "
                "and Esc both give command 1. The Random Event pop-ups and the tip window take no key at all.", C),
        Fact(g, "Message boxes: command 1 is the Yes button (or OK) and command 2 the No button (or Cancel), so "
                "Enter answers Yes or OK and Esc answers No or Cancel.", C, sub=True),
        Fact(g, "The purchase dialog: Enter and Esc both close it without buying; only clicking its buy button "
                "(command 3) buys.", C, sub=True),
        Fact(g, "The family tree name and the new player's nickname dialogs: Enter is OK (the name is kept), Esc "
                "closes without it.", C, sub=True),
        Fact(g, "While a dialog's name box has the typing cursor, Enter does nothing: the box gets each key before "
                "its dialog does (the newest window to open is asked first) and keeps every key except Esc for "
                "itself. Esc still reaches the dialog.", C, sub=True),
        Fact(g, "What a name box takes: only plain letters, digits, spaces and ASCII punctuation. A typed character "
                "that is anything else (an accented letter, an Alt code, an input method's word) never arrives: the "
                "game drops any typed text longer than one byte, and a box refuses every byte from 128 up. The "
                "family name box takes 20 characters and keeps 19 (the 20th is cut when you press OK).", C,
             sub=True),
        Fact(g, "How the game draws text: four fonts (pictures of white letters it tints to the colour wanted), "
                "each with the same 190 letters: the space, A to Z, a to z, digits, ASCII punctuation and the "
                "Latin-1 accented letters and signs from ¢ to ÿ. A byte it has no letter for is drawn as "
                "“!”. Ten more font pictures (and four copies of the used ones, laid out 512 pixels wide) "
                "are in its Images folder but never drawn.", C, sub=True),
        Fact(g, with_patcher("RenderUnicodeInGameFonts", "every name box takes any character the keyboard gives "
                             "(accent keys, dead keys, Alt codes, an input method's text), Backspace deletes a whole "
                             "character, and a name is kept as UTF-8 in the same room, never cut inside a "
                             "character (a family name holds 19 plain letters, fewer accented or other ones). All "
                             "text is drawn with the game's own fonts, with patcher-made letters in the same style "
                             "for the ones they lack. The stock game shows such a name as other Latin-1 letters, "
                             "one per byte, and saves it unchanged."), E, sub=True),
        Fact(g, "Opening logos: any typed key or a click moves on to the next logo (each also moves on by itself "
                "after 4 seconds of real time). F1 skips the rest of the logos and the loading screen and opens the "
                "house at once.", C),
        Fact(g, "What the house does when F1 has skipped the loading screen: the loading screen is what sets up "
                "the house map, the collectibles, the pictures and the family over six steps, and F1 leaves all of "
                "them undone. Only a live game run shows what follows, and this page is built without running the "
                "game.", U, sub=True),
        Fact(g, "Cheat codes: there are none. Nothing compares what you type with a hidden word; the only typed "
                "text the game checks is a new player's name against NEW PLAYER (the box's starting text). No "
                "other key does anything on the main menu, the Adoption, Dating, Trophies, Family, Collections or "
                "Help screens than the ones above.", C),
        Fact(g, "Settings in ldw.ini (in the game folder), the only outside switches the game reads: under [ldw], "
                "FullScreen (shipped as 1) and ForceFullScreen start in full screen, ForceWindowed starts in a "
                "window (either Force setting also hides the Options full-screen choice), ForceStaticSplash shows "
                "still opening logos; under [LDW], Distributor adds a name to the version line on the main menu. "
                "None unlocks a key or a cheat. The game reads no registry value and ignores its command line.", C),
        Fact(g, "DEAD (never runs): three developer tools are left in the game: an animation aligner (it asks "
                "before deleting a step of an animation and shows its playing speed), a light source editor "
                "(\"Light Source Editor Enabled (F4 to exit)\", L adds a light, D deletes one) and a waypoint editor (\"Waypoint Editor "
                "Enabled\", with keys S and W). The aligner is built when the game loads but no "
                "button, key or code ever switches to it; the two editors are created when the game starts but "
                "nothing ever uses them again, so their keys are never read. None can be reached in the shipped "
                "game.", C),
        Fact(g, "The Fun Patcher's keys: one patcher key in the game itself, R in the store (R Refreshes the Store, "
                "above); it adds no other key, click spot or typed code. Its own windows (the Upgrades menu pages) "
                "close with Enter or Esc, as ordinary Windows dialogs.", C),
        Fact(g, with_patcher("StoreRefreshKey", "patcher key R, in the store only: see the store's hidden key above."),
             E, sub=True),
        Fact(g, "Random tips, click spot: clicking a small spot just below the house view at the left of the bottom "
                "bar (51 by 23 pixels: across from 171 to 221 and down from 562 to 584 on the 800 by 600 game "
                "screen) shows a random tip in the message bar, with a wooden click. Every click picks again from "
                "all 50 tips (tips 1 to 18: " + _odds(0, 50) + " each; tips 19 to 50: " + _odds(18, 50) + " each), "
                "with no wait and no limit, so the same tip can come twice running.", C),
        Fact(g, "What is at that spot: nothing of its own. The house screen's border picture (Images\\main_BG.png, "
                "which the house loads beside the spot's coordinates) has there a plain stretch of the light blue "
                "edge below the bottom bar's left boxes and the top of the dark blue panel under it; no code places "
                "any picture at those coordinates.", C, sub=True),
        Fact(g, "Random tips, loading screen: each time the game starts, its loading screen shows one of tips 1 to "
                "30 (tips 1 to 8: " + _odds(0, 30) + " each; tips 9 to 30: " + _odds(8, 30) + " each).", C),
        Fact(g, "The 50 random tips, as the game words them:", C),
        *tips,
        Fact(g, "First-time tips (the tip window): a tip already seen is not shown again, and at most 10 wait "
                "in line. The first time a screen opens it shows its own: Adoption (\u201cWow! There are so many needy "
                "little people living in your computer.\u201d ...), Store (\u201cWelcome to the Store.\u201d ...), "
                "Details (\u201cWelcome to the Detail Screen.\u201d ...), Family (\u201cWelcome to the Family "
                "screen!\u201d ...), Trophies (\u201cWelcome to the Trophies screen!\u201d ...), Collections "
                "(\u201cWelcome to the Collections screen!\u201d ...) and the marriage proposal (\u201cWow! It's an "
                "incoming marriage proposal!\u201d ...).", C),
        Fact(g, "The other tutorial tips (39 tip texts in all) and what queues each one, from the code that "
                "names it:", C, sub=True),
        *[Fact(g, text, C, sub=True) for text in TUTORIAL_TIPS],
        Fact(g, "Clicking things in the house (a click on a spot with nobody on it; the places are the game's own "
                "click map):", C),
        Fact(g, "the refrigerator: shows \u201cFood available:\u201d and how much food there is, with a door "
                "sound.", C, sub=True),
        Fact(g, "the kitchen trash can: shows \u201cTrash:\u201d and the trash count, with the lid sound.", C,
             sub=True),
        Fact(g, "the TV wall in the living room: turns the TV on, or off again (which also stops everyone watching "
                "it); only while the TV remote is in its place, otherwise nothing.", C, sub=True),
        Fact(g, "the bathroom's two sinks: turns both taps off when both are running; the kitchen sink: turns its "
                "tap off when it is running.", C, sub=True),
        Fact(g, "the office desk: switches off the office's two computers when they are on. They are the two "
                "office effects that the computer actions switch on as they start and off as they end: Working on "
                "career (in the Office), Playing office, Chatting online, Selling a collectible online and Fixing "
                "the computers; one left on stays on until a click or another of those actions ends it.", C,
             sub=True),
        Fact(g, "the office computer: an office machine sound, then \u201cRouter error!\u201d while the router "
                "malfunction is on (family members call it \u201cThere is no Internet!\u201d), otherwise "
                "\u201cStatus: online\u201d.", C, sub=True),
        Fact(g, "the hall cabinet: \u201cCollectibles Found:\u201d and how many of the 48 different collectibles "
                "the family has found (\u201c... / 48\u201d).", C, sub=True),
        Fact(g, "sounds only: the end table by the sofa plays the radio once the Radio and MP3 Player is bought; "
                "the washer and dryer corner plays pinball once the Pinball Machine is bought; the stove and the "
                "counter beside it play a blender and a mixer with the Kitchen career room at level 2 or 3; the "
                "near end of the office desk plays wood scraping with the Office career room at level 3.", C,
             sub=True),
        Fact(g, "The TV remote: a new family's remote starts lost, lying at a random spot on the ground. Drop a "
                "family member on it (within 30 pixels) and they start \u201cReturning the TV remote\u201d. If "
                "they carry it to the living room's coffee table it stays there for 23 to 28 hours of real "
                "time: it goes missing again at the start of the 24th to 28th whole hour of real time after the "
                f"hour it came back ({_odds(0, 5)} each for the 24th, 25th and 26th, {_odds(3, 5)} for the 27th and "
                "28th), at a new random spot. If they end anywhere else it is lost again at once at a new spot "
                "(checked every 2 seconds of real time).", C),
        Fact(g, "While the remote is lost, TV Night never happens and clicking the TV does nothing.", C, sub=True),
        Fact(g, "The shed door: a new family's shed door needs fixing; its spot is at the front corner of the deck "
                "by the sandbox. Drop a family member older than 14 years (more than 280 age units) on it and they "
                "start \u201cFixing the shed door\u201d (a younger one does not start it). If they "
                "finish at the shed's doorway the door is fixed, otherwise it still needs fixing; a fix still under "
                "way when the game is closed is lost. Once it is fixed, a family member dropped on the shed starts "
                "\u201cUnlocking shed door\u201d, which opens the shed for good and gives a trophy.", C),
        Fact(g, "The trophy is \u201cThe shed\u201d (\u201cYou managed to open the shed.\u201d): the code gives "
                "trophy 60, and the trophy table's row 60 names it (every row's title is the game's text number "
                "462 + 2 x the row; see Trophies and the heir).", C, sub=True),
    ]


def _time() -> list[Fact]:
    g, E, C, U = TIME, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Game speed: the game only ever runs at Normal.", C),
        Fact(g, with_patcher("CheatUpgrades", "the Time Controls page adds Slow (half speed), Fast (double speed), "
                                              "5x and 10x."), C, sub=True),
        Fact(g, with_patcher("CheatUpgrades", "Time Controls speeds never reach a save: the game saves a family at "
                                              "Normal (or Paused) and loads any other saved speed as Normal. So the "
                                              "time while the game is closed is always counted at Normal, for "
                                              "ageing and for game time."),
             C, sub=True),
        Fact(g, f"Ageing runs on game time: one age unit every {units_span(1)}. Twenty age units are one year: "
                f"{units_span(YEAR_UNITS)}.", E),
        Fact(g, "How ageing is counted: each family member counts the real seconds since their last update and "
                "divides them by 60 x the speed value, so an age unit is 10 minutes of game time at every speed. "
                "It is kept by each family member, not by the game clock below, and it also counts the time the "
                "game is closed, at Normal, within the time-away limits below.", C),
        Fact(g, "Paused: the game clock stops, so nothing that runs on game time moves (interest, events, the "
                "dating e-mail, the half-price grocery, messes, the sky); collectibles stop too.", C),
        Fact(g, "Paused, real time runs on: the store's Flea Market, food groups, symptoms and the wait between babies "
                "keep counting down in real time, and every 2 seconds of real time the family update, the house "
                "malfunction roll and the autosave check still run (the family update then ages nobody).", C),
        Fact(g, "Paused: nobody ages, and the paused time is never added on later (checked with 3 days of real "
                "time paused: no ageing at all).", E),
        Fact(g, "Day and night follow your PC's clock, in real time (12 hours later with Reverse Day/Night), at "
                "every speed and also while paused.", C),
        Fact(g, "Game time also runs while the game is closed: the game clock is saved with the real time of the "
                "save and, when the family is loaded, counts on from the real clock at the saved speed (always "
                "Normal) with no limit; a family saved paused keeps its game clock stopped. So on loading, every "
                "missed game day of interest is paid at once, and the event check, the dating e-mail and each "
                "store draw come at most once.", C),
        Fact(g, "Messes owed for the time the game was closed appear when it is loaded, all at once: the mess "
                "timer (game time) is saved with the house's messes and loaded back, and the game clock counts the "
                "closed time, so the first update counts every mess due since then and fills free places with "
                "them, up to the 30 places.", C),
        Fact(g, "Time away for ageing, while the game is closed (real time away, counted at Normal, see above):",
             E),
        Fact(g, "up to 8 hours 36 minutes 40 seconds (31,000 seconds) of real time away: counted in full.", E,
             sub=True),
        Fact(g, "longer than that, up to exactly 24 hours of real time: counted as 8 hours 36 minutes 40 seconds "
                f"({31_000 // (AGE_UNIT_SECONDS * NORMAL)} age units, about 2.6 years).", E, sub=True),
        Fact(g, "more than 24 hours of real time: counted as 24 hours (144 age units, 7.2 years).", E, sub=True),
        Fact(g, "at Slow the same check counts in full up to 6 hours 36 minutes 40 seconds of real time, then 8 "
                "hours 36 minutes 40 seconds up to 24 hours; at Fast in full up to 10 hours 36 minutes 40 seconds, "
                "then 8 hours 36 minutes 40 seconds; more than 24 hours is 24 hours at every speed.", E, sub=True),
        Fact(g, "a gap is caught up all at once: every counted age unit runs its hunger, health, sickness, "
                "birthday and birth checks before the house is drawn again.", E, sub=True),
        Fact(g, "\"Where have you been?\" is shown after 24 hours or more of real time away (the whole hours away "
                "must be more than 23), but not for a family saved paused.", C, sub=True),
        Fact(g, with_patcher("CheatUpgrades", "Time Warp on the Time Controls page ages everyone at home 61 age "
                                              "units (3 years and 1 unit) at once, past the time-away limits above, "
                                              "running every unit's checks; the money gained in a warp stops at $750 "
                                              "more than before it. It works while paused too."), E),
    ]


def _needs() -> list[Fact]:
    g, E, C, U = NEEDS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Every 2 seconds of real time the game updates the family, at every speed and also while paused.",
             C),
        Fact(g, "Each family member at home and alive then runs the checks below once for every age unit they "
                "have aged since.", E),
        Fact(g, f"Hunger: +5 every 4 age units ({units_text(4)}); above 80 it rises by 2 instead.", E),
        Fact(g, "Hunger never goes above 100.", C),
        Fact(g, "Eating, each age unit: a hungry family member (hunger over 50) eats 3 food and loses 3 hunger - "
                "always with more than 50 food in the house, 50.05% of the time with 50 or less.", E),
        Fact(g, upgrade("Food Club", "$10,000", "when a hungry family member is about to eat and there is less than "
                                                "60 food in the house, 60 food is added first, so they always eat "
                                                "(checked: 30 food becomes 87 after the meal, 0 becomes 57)."),
             E, sub=True),
        Fact(g, "Not eating (no food at all, or the missed 50.05% with 50 food or less): 30.03% chance of losing 1 "
                "health (recorded as Starvation).", E),
        Fact(g, "Waste: with 1,000 food or more, a hungry family member has a 76.05% chance each age unit of "
                "using 3 more food.", E),
        Fact(g, "Bathroom need (\"poo\" in the save): at 90 or more it drops to 25 to 49.", E),
        Fact(g, "Food groups on this page are as counted for a family member with a career: each active group "
                "once.", E),
        Fact(g, "Health, happiness and sickness are checked every 3 age units "
                f"({units_text(3)}).", E),
        Fact(g, "Energy (every other age unit, only the last 12 of a catch-up; the hours are your PC's clock, real "
                "time): -4 between 8 PM and 5 AM (from 10 "
                "energy up); +8 between 5:06 AM and 5 PM (up to 70 energy); -1 each for happiness 10 or less, "
                "health 25 or less, health 10 or less, hunger 90 or more; -3 if sick; at most -6 / +10 a time, "
                "halved below 10 and above 80, kept 1 to 100.", C),
        Fact(g, "Happiness (every 3 age units) follows a hidden trend built from: how happy they are now, food "
                "groups, money (under $1,000 and under $100 lower it, over $8,000 raises it), food (250 or "
                "less, 50 or less lower it), sickness, the house's mess, every house upgrade owned (+10 each), "
                "upgrades they like, their liked career rooms' levels, careers, family size, the couple's "
                "matching wish for children, hunger 90+ and health 10 or less. Each update moves happiness by "
                "at most 5.", C),
        Fact(g, "Food groups: Grains, Dairy, Meats, Fruits and Veggies. Putting a bag in the kitchen gives that "
                "group to every family member at home for 24 hours of real time, at any speed, also while paused "
                "and while the game is closed. Groceries add 150 food, "
                "organics 250 food and a little happiness.", E),
        Fact(g, "Food in the house starts at 50 to 99, never goes below 0 when food is taken away and has no top "
                "limit. Food only changes "
                "through eating, bags and events - there is no daily use.", C),
        Fact(g, "Food added past 2,147,483,647 wraps round to a large negative number (checked: 2,147,483,600 "
                "plus 150 gives -2,147,483,546).", E),
        Fact(g, with_patcher("ClampMoneyAndFood", "food that has wrapped below 0 is put back to 2,147,483,647 in the "
                                                  "next frame (frames run on real time), so food stays at most "
                                                  "2,147,483,647."), E, sub=True),
        Fact(g, upgrade("Food Club", "$10,000", "+500 food and all four food groups for every family member at home "
                                                "(for 24 hours of real time) once a game day, every "
                                                f"{game_span(86_400)}; every missed game day is delivered at once, "
                                                "the game days while the game was closed included, with no limit "
                                                "(checked: 1, 2, 30 and 100 game days give 500, 1,000, 15,000 and "
                                                "50,000 food)."), E),
        Fact(g, "The info panel's bars show happiness, 100 minus hunger (\"Fed\"), energy and health.", C),
        Fact(g, "On the info panel each label sits beside its own bar, top to bottom: Happiness (label 210 and bar "
                "208 pixels down), Health (250 and 247), Fed (289 and 286) and Energy (328 and 326); the labels are "
                "at 458 pixels across, the bars at 473.", C),
    ]


def _health() -> list[Fact]:
    g, E, C = HEALTH, VERIFIED_E, VERIFIED_C
    return [
        Fact(g, "Health check, every 3 age units: -1 if happiness is 10 or less; -1 if hunger is 90 or more and "
                "another -1 at 100; -1 with exactly 1 food group, +1 with exactly 4; if sick, -1 with a 15.01% "
                "chance (symptoms only) or 40.04% (with an infection). The total is kept between -5 and +5 and "
                "recorded as Unknown causes.", C),
        Fact(g, "Health limits: below 15 health every loss is halved, rounding toward zero, so a 1-point loss is "
                "dropped; above 90 every gain is halved and a 1-point gain is dropped. Health is kept 0 to 100.", E),
        Fact(g, "Recovery, each age unit with food in the house and no sickness: 50.05% chance of +1 health; "
                "from age 55, 10.02%. A +1 never takes health above 91.", E),
        Fact(g, "Sick, each age unit: 61.06% chance of losing 1 health (recorded as Disease); at health 20 or "
                "less, 18.95%.", E),
        Fact(g, "No food at all, each age unit: 76.05% chance of losing 1 health (recorded as Starvation). For "
                "family members whose name number is a multiple of 6 the loss is certain; at health 20 or less, "
                "those whose name number is odd (and not a multiple of 6) then have a 31.03% chance of +1.", E),
        Fact(g, "The per-unit Starvation and Disease losses are 1 point each, so they stop at 14 health.", E),
        Fact(g, "A starving family member still dies: the health check takes 2 points at hunger 100 (1 below 15 "
                "health) until health reaches 0. That death is recorded as Unknown causes (checked: from 14 "
                f"health, 0 after 90 age units, {units_text(90)}; even with every per-unit loss missed).", E),
    ]


# FoodGroupsActive 0x48FE30 (emulated 2026-10-25): its fifth slot's flag is the low byte of the Grains expiry and
# its expiry is the career id, which for no career (-1) never runs out.
EXTRA_GROUP = ("A family member without a career (every child) counts one extra food group once they have had "
               "Grains, even after those Grains run out (except about 1 time in 256). With a career the count is "
               "exact.")


def _sickness() -> list[Fact]:
    g, E, C, U = SICKNESS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, f"A healthy family member is checked every 3 age units ({units_text(3)}). Chance of falling ill "
                "for a family member with a career (any sickness / a symptom / a mild infection / a serious one):",
             E),
        Fact(g, "0, 1, 2 or 4 food groups: 1.007% / 0.906% / 0.071% / 0.030%.", E, sub=True),
        Fact(g, "exactly 3 food groups: 0.806% / 0.725% / 0.056% / 0.024%.", E, sub=True),
        Fact(g, "anyone at home already has a symptom: 2.518% / 2.266% / 0.176% / 0.076%, and the symptom "
                "caught is that person's first one.", E, sub=True),
        Fact(g, EXTRA_GROUP + " Their chance of falling ill is as if they had one more group: with 4 groups and "
                "no career, 0.504% / 0.453% / 0.035% / 0.015%; with 2 groups, the 3-group row.", E),
        Fact(g, "A symptom lasts 6 to 17 hours of real time, at any speed, also while paused and while the game is "
                "closed; with only symptoms, the first one goes at the first sickness check (every 3 age units) "
                "after its time is up.", E),
        Fact(g, "Mild infection: each check, 50.05% chance of a new symptom when there is none; it ends with a "
                "3.00% chance.", E),
        Fact(g, "Serious infection: each check, 50.05% chance of a new symptom while there are fewer than 2; it "
                "ends with a 1.21% chance.", E),
        Fact(g, "Being sick: a 61.06% chance of losing 1 health each age unit, no recovery, -3 energy, a happiness trend of -150, a "
                "health-check roll, and slower unwatched work.", E),
        Fact(g, "The seven symptoms, as the Doctor Consultation's diagnosis names them, and the medicine for each: "
                "hiccups (no medicine: \"we can't help you with the hiccups\"), a sore throat (Throat Lozenges), an "
                "upset stomach (Peptic Syrup), a headache (Anti-inflammatory Pill), a cough (Antitussive Syrup), a "
                "skin rash (Cortisone Cream) and a blocked nose (Antihistamine). A mild infection needs Penicillin, "
                "a serious one Vancomycin.", C),
        Fact(g, "What each medicine, the Doctor Consultation and Baby Boost do: see Store: medicines.", E),
    ]


def _old_age() -> list[Fact]:
    g, E, C, U = OLD_AGE, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    facts = [
        Fact(g, "Old age is rolled on birthdays only. The safe age is 55 years, plus 1 year for each food group "
                "counted, 1 for the Air Purifier, 1 for the Bathroom Upgrade and 3 if health is over 90. Past it, "
                "the chance of dying on a birthday is 10 in 100 for each year over: 10.01% at 1 year over, 50.05% "
                "at 5, 100% at 10.", E),
        Fact(g, "Chance of dying on a birthday, for a family member with a career, health 90 or less, no "
                "upgrades (10.01% / 50.05% / 100% at):", E),
    ]
    for groups in range(5):
        start = 56 + groups
        facts.append(Fact(g, f"{groups} food group{'s' if groups != 1 else ''}: {start} / {start + 4} / "
                             f"{start + 9}.", E, sub=True))
    facts += [
        Fact(g, "each upgrade moves those ages 1 year later, and health over 90 moves them 3 years later.", E,
             sub=True),
        Fact(g, EXTRA_GROUP + " Their old-age odds are as if they had one more group: at 61 with 4 groups, "
                "10.01% without a career against 20.02% with one.", E),
        Fact(g, "No family member can live past 75.", E),
        Fact(g, with_patcher("OlderVillagerMortalityCurve", "the birthday roll follows the patcher's curve instead, "
                             "by years past 55 less the food groups counted (at most 4); the Air Purifier, the "
                             "Bathroom Upgrade and health over 90 no longer count. Chance of dying on a birthday "
                             "with 0 food groups: 0.37% at 56, 3.59% at 65, 7.04% at 75, 15.15% at 100, 18.19% at "
                             "110, then faster: 23.23% at 111, 56.71% at 120, 93.59% at 150, 99.73% at 200. Each food "
                             "group moves those ages 1 year later."), E),
        Fact(g, with_patcher("OlderVillagerMortalityCurve", "there is no top age: even at the highest ages 1 "
                             "birthday roll in 32,768 is survived."), E, sub=True),
        Fact(g, "A birthday that falls inside a catch-up is rolled like any other.", E),
        Fact(g, f"A body stays until 240 age units after the last update ({units_text(240)}), then is removed.",
             E),
        Fact(g, "A second piece of code also removes the body: when the dead family member's plan next starts, "
                "the death is reported and they are taken out of the house. Which of the two comes first depends on "
                "how long the death animation plays, which only a live game run shows; this page is built without "
                "running the game.", U),
        Fact(g, "Causes of death: the game stores one with each family member who dies (6 causes in its list), "
                "and only when health reaches 0:", C),
        Fact(g, "Unknown causes: reachable. Every health change that names no cause records it: the 3-unit health "
                "check (so a starving family member's death, above), Penicillin and Vancomycin, the actions that "
                "take health (Squeezing a pimple -1, Playing video games -2) and the other item uses.", C, sub=True),
        Fact(g, "Old age: reachable, the birthday roll above.", E, sub=True),
        Fact(g, "DEAD (never recorded): Disease. Its only source is the 1-point loss of being sick, and below 15 "
                "health a 1-point loss is halved to 0, so it never takes health to 0.", E, sub=True),
        Fact(g, "DEAD (never recorded): Starvation. Its only sources are the two 1-point hunger losses, which stop "
                "at 14 health the same way.", E, sub=True),
        Fact(g, "DEAD (never recorded): Work accident and Act of Nature. No code in the game passes either "
                "cause.", C, sub=True),
        Fact(g, "No cause of death is ever shown: no code in the game looks up the six cause words or the "
                "“Cause of Death” label (every instruction the game runs was searched for their numbers); "
                "the cause is only kept in the save.", C, sub=True),
        Fact(g, "Virtual Families 2's deaths from illness and from starvation (health reaching 0 while sick or from "
                "missed meals): " + NOT_IN_VF1 + ".", C, sub=True),
    ]
    return facts


def _babies() -> list[Fact]:
    g, E, C, U = BABIES, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Only the head couple has babies: the Matriarch (the first woman at home with a career) with the "
                "Patriarch. A try for a baby rolls the chance below.", C),
        Fact(g, "Family members never try for a baby on their own: none of the three try actions (Waiting for "
                "someone, Embracing, Trying to make a baby) is among the actions they choose from. Every try starts "
                "with you dropping one family member on another.", C),
        Fact(g, "The drop: both must be 18 or older (360 age units) and have a career, or nothing happens. Then, "
                "in order:", C, sub=True),
        Fact(g, "no free child place and the two are a man and a woman: “They have enough kids already!” "
                "and both shake their heads;", C, sub=True),
        Fact(g, "the wait for the next baby (below) not over: “It is too soon to try to make a baby "
                "again.”, both shake their heads, and if more than 1 hour of the wait is left it is cut to 55 "
                "minutes from that moment (real time); so once you try, you never wait more than 55 minutes;",
             C, sub=True),
        Fact(g, "otherwise they meet (Waiting for someone and Embracing) and the meeting is checked: the other one "
                "gone, dead (“That villager is dead!”), the same sex (“These villagers are both the "
                "same gender.”), either one sick (“They're not feeling well enough for this!”), under "
                "18 (“This person is too young!”) or nursing (“She's nursing a baby!”): refused;",
             C, sub=True),
        Fact(g, f"either one's hunger over 55, once the marriage proposal tip has been seen: refused "
                f"(“They're too hungry to think about this!”) {_below_pct(100, 34, invert=True)} of the "
                "time;", C, sub=True),
        Fact(g, "then they agree with a chance set by their two wish-for-children values W1 and W2 (the save's "
                "desire value, the one that also sets the wait after a birth): a roll of 105 at most 10 x (10 - "
                "W1 / 20 - W2 / 20), each division rounded down, so lower values agree more often: "
                f"{_agree(5, 5)} with both at 5 to 19, {_agree(50, 50)} with both 40 to 59, {_agree(94, 94)} with "
                "both 80 to 94. Agreed, both start Trying to make a baby, whose plan rolls the chance below; "
                "refused (“They can't agree it's time to have a baby.”), both start Arguing.", C,
             sub=True),
        Fact(g, "Every refusal at the meeting shows the tip “Too bad! They aren't in the mood. ...” and "
                "starts Arguing for both.", C, sub=True),
        Fact(g, "Chance a try works (father 30; both parents' fertility F = 1 / 25 / 50 / 75 / 100):", E),
        Fact(g, "mother 18 to 30: 39.0% / 55.1% / 73.1% / 89.0% / 100%.", E, sub=True),
        Fact(g, "mother 31: 17.0% / 33.0% / 51.0% / 67.1% / 83.0%.", E, sub=True),
        Fact(g, "mother 35: 9.0% / 25.0% / 43.0% / 59.1% / 75.1%.", E, sub=True),
        Fact(g, "mother 40: 0% / 15.0% / 33.0% / 49.0% / 65.1%.", E, sub=True),
        Fact(g, "mother 45: 0% / 5.0% / 23.0% / 39.0% / 55.1%.", E, sub=True),
        Fact(g, "mother 50: 0% / 0% / 13.0% / 29.0% / 45.0%.", E, sub=True),
        Fact(g, "mother over 50: 0%.", E, sub=True),
        Fact(g, "fathers over 40 lose 1 point for every 5 years over 40 (45: -1, 60: -4, 70: -6).", E, sub=True),
        Fact(g, with_patcher("AllowOlderPregnancies", "when either parent is 50 or older the chance is the same sum "
                             "without the mother-over-50 cut-off, but capped by the older parent's age: at most 10.07% "
                             "at 50, 5.04% at 55, 1.01% at 59, 0.91% at 60, falling to 0.10% from 68, and never below "
                             "0.10%. This also lowers the chance for a younger mother when the father is 50 or older "
                             "(mother 30, fertility 50: father 50 71.06% without the patch, 10.07% with it; father 60 "
                             "69.06% and 0.91%). Younger couples keep the chances above."), E),
        Fact(g, "Fertility is 15 to 89 when a family member is made, and kept 1 to 100.", E),
        Fact(g, "Twins and triplets: single 92.99%, twins 5.25%, triplets 1.75%; each parent's fertility over 85 "
                "adds its excess to both chances. Needs free child places (6 children per generation).", C),
        Fact(g, "How they are rolled when a try works: twins or more if a roll of 100 is below 7 + B and at least "
                "2 child places are free; then triplets if a second roll of 100 is below 25 + B and 3 are free. B "
                "is the Matriarch's fertility over 85 plus the Patriarch's fertility over 85 (0 when 85 or less). "
                "With enough free places:", C, sub=True),
        *[Fact(g, f"B = {b}" + (" (both parents at 100, the most)" if b == 30 else "") + f": single {s}, twins "
                  f"{t}, triplets {tr}.", C, sub=True) for b, s, t, tr in _twins((0, 4, 8, 10, 20, 30))],
        Fact(g, "Fertility is 15 to 89 when a family member is made, so B is at most 8 without Baby Boost; Baby "
                "Boost (see Store: medicines) raises it to 100.", C, sub=True),
        Fact(g, "With only 1 free child place a try that works is always one baby; with 2, triplets turn into "
                "twins.", C, sub=True),
        Fact(g, with_patcher("UpTo28Children", "experimental: 28 child places per generation instead of 6, as long "
                                               "as the house has a free place among its 30."), E, sub=True),
        Fact(g, f"Pregnancy lasts 21 age units: {units_span(21)}.", E),
        Fact(g, "A baby joins the family at age 2 (40 age units). While the family is 6 or fewer, the baby's sex "
                "is chosen to balance the house.", C),
        Fact(g, "Wait before the next baby (real time, at any speed, also while paused and while the game is "
                "closed): after a birth, 10 minutes to 4 hours 10 minutes, longer the less both parents want "
                "children; after a try that fails, 20 minutes and a dip in the mother's happiness; marrying clears "
                "it. Trying too soon gives the \"too soon\" response and, if the wait was more than an hour away, "
                "shortens it to 55 minutes.", C),
        Fact(g, "The wait after a birth in full: 600 seconds x (5 - W1 / 20) x (5 - W2 / 20), each division rounded "
                "down, W1 and W2 being the two parents' wish-for-children values (5 to 94 when a family member is "
                "made): 10 minutes of real time with both at 80 or more, 1 hour 30 minutes with both 40 to 59, 4 hours 10 "
                "minutes with both under 20; with no Patriarch it is 1 second. It is set only for a birth the game "
                "processes while it runs.", C, sub=True),
        Fact(g, "Its clock is the save's real-time clock (the PC's clock less the family's start): it runs at the "
                "same pace at every game speed, while paused and while the game is closed, and nothing else moves "
                "it on; only the drop described above reads it.", C, sub=True),
        Fact(g, "Virtual Families 2's longer wait after a failed try (up to 12 hours 30 minutes of real time) and its "
                "always-successful first try before the pregnancy tip: " + NOT_IN_VF1 + " (a failed try waits 20 "
                "minutes of real time, and every try rolls).", C, sub=True),
        Fact(g, f"{PATCHER_PREFIX}: no wait after a failed try when the head or the spouse is 50 or older "
                f"({setting('AllowOlderPregnancies')}), or when the couple cannot have a baby - six children "
                f"already, or a same-sex couple ({setting('PrivateRomanticTime')}).", E, sub=True),
    ]


def _careers() -> list[Fact]:
    g, E, C, U = CAREERS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    successes = (22, 100, 250, 600, 750, 1000, 1500)
    facts = [
        Fact(g, "A family member made older than 16 gets one of 108 careers at random; one made at 16 or "
                "younger gets none.", C),
        Fact(g, "Levels: " + ", ".join(LEVELS) + ".", C),
        Fact(g, "A piece of work succeeds with a chance by level: 56.30% / 62.56% / 68.82% / 75.07% / 81.32% / "
                "87.55% / 93.77% / 100% (Beginner to Master).", E),
        Fact(g, "How often a family member goes to work: going to work is one of the actions they choose from, "
                "Working on career (one for each room). Each time they pick what to do next, the pick is a weighted "
                "draw among every action they may do then; the work action may be picked only in the daytime, by "
                "a family member aged 18 or older (360 age units) whose career is in that room, who is not "
                "pregnant and not sick, with hunger 75 or less and energy 20 or more. Its weight starts at 500 "
                "(the default for an action is 1,500), counts three times when they like the room's own like "
                "(cooking for the Kitchen, computers for the Office, tools for the Workshop) and a quarter when they "
                "dislike it, and the praise and scolding gloves move it between 50 and 45,000.", C),
        Fact(g, "Working on career plans: a piece of career work (the success roll above), energy -2 twice, "
                "dirtiness +1 and hunger +1 (see Actions).", C, sub=True),
        Fact(g, "Each success pays 3% of the salary and adds progress; promotion at 3,000 progress (everyone "
                "celebrates). Successes per promotion with the career room at level 1: "
                + ", ".join(f"{n:,}" for n in successes) + "; at level 2 half as many; at level 3 "
                "8, 34, 84, 200, 250, 334, 500.", E),
        Fact(g, "Salary is paid every 3 age units (30 minutes of game time) whether or not the family member is at "
                "work, an eighth of the salary each time: a quarter of the salary per hour of game time (1 hour of "
                "real time on Normal, 2 hours on Slow, 30 minutes on Fast).", E),
        Fact(g, "During a catch-up, a grown-up with a career who is not sick or pregnant also gets unwatched work "
                "each age unit, each piece with a 1 in 6 (16.67%) chance of a paid success.", C),
        Fact(g, "How much unwatched work: one piece for every 400 of the weight of their room's Working on career "
                "action (above), rounded down: 1 at the starting weight of 500, 112 at the top weight of 45,000.",
             C, sub=True),
        Fact(g, "Virtual Families 2's 132 careers, its Advanced Career Training and Career Change services and its "
                "31 career upgrades: " + NOT_IN_VF1 + " (108 careers, three career rooms with three levels).", C),
        Fact(g, "The three career rooms: room 1 is the Kitchen, room 2 the Office and room 3 the Workshop (the "
                "promotion step reads the Kitchen's level for room 1, the Office's for room 2 and the Workshop's for "
                "room 3, and each Profession Magazine works only for its own room). Upgrading them: see Career Room "
                "Upgrades.", C),
        Fact(g, "Every career's pay per hour of game time (a quarter of its salary; 1 hour of game time is 1 hour "
                "of real time on Normal), at each level from Beginner to Master, with its career room (1 Kitchen, 2 "
                "Office, 3 Workshop):", C),
    ]
    facts += [Fact(g, f"{c.name} (room {c.room}): ${_hourly(c.salaries[0])} per hour of game time as a Beginner, "
                      f"${_hourly(c.salaries[-1])} as a Master (levels: "
                      + ", ".join(_hourly(s) for s in c.salaries) + ").", C, sub=True)
              for c in CAREER_LIST]
    return facts


def _hourly(salary: int) -> str:
    """A salary as pay per hour of game time: salary / 8 every 30 game minutes, so salary / 4 an hour."""
    return f"{salary / 4:g}"


def _money() -> list[Fact]:
    g, E, C, U = MONEY, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "A new family starts with $50 to $189.", C),
        Fact(g, "Money never goes below $0: a payment that would leaves $0.", E),
        Fact(g, with_patcher("ClampMoneyAndFood", "money is kept at no more than $4,000,000,000, checked every "
                                                  "frame (real time); without it there is no top limit."), E, sub=True),
        Fact(g, f"Interest: 10% of the money a game day, every {game_span(86_400)}.", C),
        Fact(g, upgrade("Brokerage Account", "$10,000", "interest is 11% a game day ($110 on $1,000), a game day being "
                                                        "24 hours of game time. Buying it again drops the rate to 1%, "
                                                        "and each purchase after that adds 2 points, up to 11%."),
             E, sub=True),
        Fact(g, with_patcher("CheatUpgrades", "the interest-rate cheat sets any rate from 1% to 11% for every family; "
                                              "while it is set it is used instead of the Brokerage Account's "
                                              "(checked: 5% pays $50 on $1,000, also with the Brokerage Account)."),
             E, sub=True),
        Fact(g, "Interest has no limit on missed days: every whole game day (24 hours of game time) since it was "
                "last due is paid at once, 10% of the money for each day, the game days while the game was closed "
                "included (checked: 1, 2, 3, 7, 30 and 100 game days on $1,000 pay $100, $200, $300, $700, $3,000 "
                "and $10,000).", E),
        Fact(g, "Interest is paid when the family's happiness updates (every 3 age units), and when the bank, the "
                "store or an event checks it.", C),
        Fact(g, "Paused, no interest builds up: it runs on game time.", C),
        Fact(g, "Virtual Families 2's limit of 2 missed game days of interest: " + NOT_IN_VF1 + ".", C, sub=True),
        Fact(g, f"The store: the Flea Market is drawn again when the store page opens more than {SPECIALS_REAL} "
                "after the last draw; one grocery bag is half price, drawn again when the store page opens more "
                f"than {game_span(SALE_GAME_SECONDS)} after the last draw.", C),
        Fact(g, upgrade("Food Club", "$10,000", "the eight grocery and organic bags cost half, rounded down "
                                                "(Grains groceries $20 for $10, Meats organics $160 for $80)."),
             E, sub=True),
        Fact(g, upgrade("Health Plan", "$10,000", "the eight medicines, Baby Boost and the Doctor Consultation cost a "
                                                  "quarter, rounded down (Penicillin $45 for $11, Baby Boost $500 for "
                                                  "$125, Doctor Consultation $175 for $43)."), E, sub=True),
    ]


def _leaving() -> list[Fact]:
    g, E, C, U = LEAVING, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "A family member with no career leaves home when they turn 19. One with a career stays. Nobody "
                "leaves while the game is paused.", E),
        Fact(g, "Children never get a career, so every child who is not chosen as the heir leaves home at 19.", E),
        Fact(g, "After leaving they keep their place in the save but never age or update again and can never be "
                "the Matriarch or Patriarch; the family size the game counts still includes them.", C),
        Fact(g, "The Talent Scout (a Popup Event; it comes only while a child under 14 is at home): its first "
                "choice sends that child away from home, the same way, and pays +$500; its second choice does "
                "nothing.", E),
        Fact(g, "What the game calls leaving home: nothing is shown. The game has the words “{name} is going "
                "to college!” and the tip “One of the children is now old enough to go to college!”, "
                "but no code in the game loads either one (every instruction the game runs was searched for their "
                "numbers).", C),
        Fact(g, "Virtual Families 2's Boarding School service and its e-mails from children who left: "
                + NOT_IN_VF1 + ".", C),
    ]


def _marriage() -> list[Fact]:
    g, E, C, U = MARRIAGE, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "The first head of the family is 24 to 29 years old, man or woman at random.", C),
        Fact(g, f"The first dating e-mail comes {game_span(180)} after the head (or heir) joins. After the dating "
                "page is opened, the next is 5 minutes of game time later for each proposal so far plus 10 minutes "
                "of game time for each year the head is over 26. It comes only when exactly one family member aged "
                "14 or more is at home.", C),
        Fact(g, "Each candidate is the opposite sex, 3 years younger to 2 years older than the head, with a "
                "dowry of $35 to $209, doubled 15.01% of the time. Asking for another candidate loses this "
                "one.", C),
        Fact(g, with_patcher("CheatUpgrades", "once Enable Same-Sex Marriage is switched on for the family on the "
                                              "Family page, every candidate is the same sex as the head."),
             E, sub=True),
        Fact(g, "Marrying pays the dowry, puts the spouse in the family tree and clears the wait for a baby.", C),
        Fact(g, "The next generation: when a parent with children dies and a child is still alive, the family "
                "tree offers it. Choosing an heir hides every other family member. Nobody remarries while "
                "there are children in the record.", C),
        Fact(g, with_patcher("AllowOlderPregnancies", "the family tree also offers the next generation, with no "
                                                      "death, while a child is alive and the oldest family member "
                                                      "at home is 60 or older."), E, sub=True),
        Fact(g, "At most 6 children per generation, 30 family members in a save and 30 generations.", C),
        Fact(g, with_patcher("UpTo28Children", "experimental: at most 28 children per generation; the family tree "
                                               "still holds only the first 6."), E, sub=True),
        Fact(g, "Adoption Day (a Popup Event): everyone celebrates; nobody joins or leaves.", E),
        Fact(g, "The Little Visitor (two Popup Events, one with a boy and one with a girl; each comes only while "
                "someone is at home and a child place is free): its first choice adds a 3-year-old (60 age units) "
                "boy or girl to the house and to the family tree as a child of the generation, and counts toward "
                "the “Four is enough” and “No vacancy” trophies; its second choice does "
                "nothing.", C),
    ]


# (title, kind, effect, label): docs/game-mechanics/spec.md section 11 (events_registry.tsv, events_emulated.txt)
_EVENTS = (
    ("1 A Secret Admirer", "Email Event", "nothing seen", VERIFIED_E),
    ("2 / 3 Electric Bill Correction", "Email Event", "-$5 to $24 / +$5 to $24", VERIFIED_E),
    ("4 Spam \"Funny\"", "", "never comes", VERIFIED_C),
    ("5 / 6 Professional Association Fee / Rebate", "Email Event", "-$5 to $7 / +$5 to $14", VERIFIED_E),
    ("7 Professional Network", "Email Event", "20 pieces of unpaid career progress for a family member picked at "
     "random among those aged 14 or older with a career who are not pregnant (a Beginner with the room at level 1 "
     "gains 2,800 of the 3,000 a promotion needs); it comes only while there is one", VERIFIED_C),
    ("8 Professional Association Award", "Email Event", "a promotion for a family member picked the same way, with "
     "its new salary (a Master gets none); it comes only while there is one", VERIFIED_C),
    ("9 Infringement Complaint", "Email Event", "a family member picked the same way loses all the progress toward "
     "their next promotion (it is set to 0); no money changes; it comes only while there is one", VERIFIED_C),
    ("10 / 11 Tax Audit", "Email Event", "-$100 / +$100", VERIFIED_E),
    ("12 to 15 Spam (Bigger Brain, Nigerian Lottery, Car Insurance, What's What)", "Email Event", "nothing", VERIFIED_E),
    ("16 to 18 Old Friend", "Email Event", "nothing", VERIFIED_E),
    ("19 Oh! A collectible!", "Email Event", "a rare collectible", VERIFIED_C),
    ("20 My Weather Machine", "Email Event", "the sky turns Raining at once and is held there for 30 seconds of game "
     "time, then the rain runs its own 6 to 12 minutes of game time (see Weather); it comes only while the sky is "
     "Normal or Sunny", VERIFIED_C),
    ("21 An extra hammock", "Email Event", "everyone goes to the yard", VERIFIED_E),
    ("22 Birthday present, 23 Preferred Customer Rebate, 24 Craft Fair", "Email Event",
     "+$10 to $50 / +$5 to $79 / +$35 to $45", VERIFIED_E),
    ("25 / 26 The Rebate", "Email Event", "nothing / +$50", VERIFIED_E),
    ("27 Helpful Child, 28 Bad Cookies", "Email Event", "+$5 to $54 / -$5 to $100", VERIFIED_E),
    ("29 / 30 Office Collection, 33 Overdue Book, 35 Bake Sale", "Email Event",
     "-$4 to $40 / -$5 to $50 / -$5 to $50 / -$6 to $60", VERIFIED_E),
    ("31 Best Landscape Award, 32 Kite Contest, 34 Hot Dog Contest", "Email Event", "+$5 to $50 / +$8 to $80 / +$5 to $50",
     VERIFIED_E),
    ("36 Neighborhood Children's Association", "Popup Event", "-$20 (with 2 children)", VERIFIED_E),
    ("37 Earthquake", "Popup Event", "each of the three floor spots that has been repaired breaks again with a "
     f"{_below_pct(100, 40)} chance (each rolled on its own), so its repair can start again; it comes only while at "
     "least one of the three is repaired; no money changes", VERIFIED_C),
    ("38 Aesthetic Society", "Popup Event", "-$5 for every weed in the yard; it comes only while there is at least "
     "one weed; no other money condition", VERIFIED_C),
    ("39 Birdwatcher Society", "Popup Event", "+$25, $50, $75 or $100", VERIFIED_E),
    ("40 Allergy Season", "Popup Event", "three picks, each a family member at home at random (the same one can "
     "be picked again), and each one picked gets a blocked nose (a symptom, 6 to 17 hours of real time): 1 to 3 "
     "family members", VERIFIED_E),
    ("41 Adoption Day", "Popup Event", "everyone celebrates", VERIFIED_E),
    ("42 TV Night, 43 BBQ Party", "Popup Event", "everyone joins in (needs the item)", VERIFIED_E),
    ("44 The Broken Window", "Popup Event", "+$1 to $30", VERIFIED_E),
    ("45 Photo Contest, 46 Community Association", "Popup Event", "+$25 to $125 / -$20 to $100", VERIFIED_E),
    ("47 Blowing Trash, 48 Free Lawn Service", "Popup Event", "5 to 12 wrappers in the house / 5 to 12 weeds in the yard",
     VERIFIED_E),
    ("49 / 50 The Little Visitor", "Popup Event", "first choice: a 3-year-old boy (49) or girl (50) joins the "
     "house and the family tree; it comes only while a child place is free", VERIFIED_C),
    ("51 Small Package", "Popup Event", "first choice: one of the six symptom medicines (Throat Lozenges, Peptic "
     f"Syrup, Anti-inflammatory Pill, Antitussive Syrup, Cortisone Cream, Antihistamine), {_odds(0, 6)} or "
     f"{_odds(5, 6)} each, into the item tray for free; it comes only while the tray has a free place",
     VERIFIED_C),
    ("52 Medium Brown Box", "Popup Event", "first choice: one of the four grocery bags (Grains, Dairy, Meats, "
     "Fruits and Veggies), 25.00% each, into the tray for free; only while the tray has a free place", VERIFIED_C),
    ("53 Sealed Green Bag", "Popup Event", "first choice: one of the four organics bags, 25.00% each, into the tray "
     "for free; only while the tray has a free place", VERIFIED_C),
    ("54 A Tiny White Box", "Popup Event", "first choice: a third of the food is gone", VERIFIED_E),
    ("55 Scratch-Off Lottery Ticket", "Popup Event", "first choice: -$20, then a win "
     f"{_below_pct(100, 33)} of the time of $10 to $100 in $10 steps (10 prizes, {_odds(0, 10)} or {_odds(9, 10)} "
     "each), which also counts toward the “Lucky winner” trophy; a loss pays nothing; it comes only while "
     "the family has more than $21", VERIFIED_E),
    ("56 The Wrong Address", "Popup Event", "first choice: -$100 and the Sheets and Pillows home improvement; it "
     "comes only while the family has no Sheets and Pillows and has $99 or more", VERIFIED_C),
    ("57 The Delivery Truck", "Popup Event", "first choice: the Collection of Paintings home improvement for free "
     "(it also counts toward the “Retail therapy” and “Dreaming of Isola” trophies); second "
     f"choice: +$20 to +$160 in $20 steps ({_odds(0, 8)} each); it comes only while the family has no Collection of "
     "Paintings", VERIFIED_C),
    ("58 The Talent Scout", "Popup Event", "first choice: a child under 14 picked at random leaves home and the "
     "family gets +$500; it comes only while there is one", VERIFIED_E),
    ("59 The Beauty Contest", "Popup Event", "first choice: -$10, then a win of $100 "
     f"{_below_pct(100, 33)} of the time; it comes only while a child under 14 is at home", VERIFIED_E),
    ("60 Landscaping, 61 Housekeeping", "Popup Event",
     "never shown: each has choices but no family member to act on, so the game skips them (0x41AAE1..0x41AAF1)",
     VERIFIED_C),
    ("62 Total House Care", "Popup Event", "first choice: -$50 and every sock, candy wrapper, weed, cobweb and dirt "
     "smudge is removed; no money condition", VERIFIED_C),
    ("63 The Mysterious Collector", "Popup Event", "first choice: +$20 for every common, +$30 for every uncommon and "
     "+$100 for every rare collectible found, across all four collections; then every collection starts again from "
     "nothing, and the progress of the four collection trophies not yet won goes back to 0; it comes only while at "
     "least one Old Coins collectible has been found", VERIFIED_C),
    ("64 Water Pressure Surge", "Popup Event", "second choice: five leaks", VERIFIED_C),
    ("65 Professional Career Training", "Popup Event", "first choice: -$250 and a promotion for the Matriarch or the "
     f"Patriarch (the Patriarch is tried first {_below_pct(100, 50)} of the time, the Matriarch otherwise, and the "
     "other one when the first is missing); it comes only while the family has more than $255", VERIFIED_E),
    ("66 The Trainer", "Popup Event", "first choice: -$5 and all the food is gone", VERIFIED_E),
    ("67 The Cooking Class", "Popup Event", "first choice: a kitchen mess", VERIFIED_C),
    ("68 The Power Failure", "Popup Event", "first choice: food set to 50 to 99; second: a family member gets a symptom",
     VERIFIED_E),
    ("69 Career Change Counselor", "Popup Event", "first choice: the Matriarch or the Patriarch (picked as for 65) "
     "gets a new career drawn from all 108, 1 in 108 each, at Beginner with its Beginner salary; no money changes "
     "and no money condition", VERIFIED_E),
    ("70 The Rare Bird", "Popup Event", "first choice: -$235 to -$305 (in steps of $10) and the Birdhouse home "
     "improvement; it comes only while the family has no Birdhouse", VERIFIED_C),
    ("71 School Fund-raiser", "Popup Event", "first choice: -$25 and +100 food", VERIFIED_E),
)


def _events() -> list[Fact]:
    g, C, U = EVENTS, VERIFIED_C, UNCONFIRMED
    facts = [
        Fact(g, f"An event is checked every {game_span(3_600)}. The first check comes {game_span(900)} after "
                "a new family starts. Paused, none come. The next check is set from the time of the check, so after "
                "the game was closed at most one comes at once.", C),
        Fact(g, "At each check a random family member is picked; if they are alive, caught up and no e-mail is "
                "waiting, it is an Email Event 66.06% of the time and a Popup Event 33.94%. Otherwise the check waits and "
                "tries again straight away.", C),
        Fact(g, "Each event that can happen is equally likely, and events repeat.", C),
        Fact(g, "The 71 Random Events (what the first and second choices do, money as a range):", C),
    ]
    facts += [Fact(g, f"{title}{f' ({kind})' if kind else ''}: {effect}.", label, sub=True)
              for title, kind, effect, label in _EVENTS]
    facts.append(Fact(g, "Virtual Families 2's own events (I Ate Soup and the other happiness e-mails, Oh So Clever, "
                         "the EPA Visit, the Chemical Manifest, the cupcake and magazine sellers, the diaper events, the "
                         "Bug Whisperer, the Collecting Contest, Adult-proof and the notes and letters): "
                         + NOT_IN_VF1 + ".", C))
    facts.append(Fact(g, with_patcher("RollTheDice", "Roll the Dice on the Upgrades menu costs $500 and brings a "
                                                     "Popup Event at once, picked from those that can happen as "
                                                     "above; when none can, the $500 is given back."), C))
    return facts


def _messes() -> list[Fact]:
    g, E, C, U = MESSES, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, f"With fewer than 4 in the family a mess appears every {game_span(18_000)}; with 4 or more, "
                f"every {game_span(9_000)}. None while paused. Up to 30 at once, house and yard together; when more "
                "than one is due, all of them appear at once.", C),
        Fact(g, "What it is: a cobweb 20.02% (when none is out), a weed in the yard 10.01% (30.03% while a cobweb is "
                "out), a sock 25.02%, a candy wrapper 24.99%, a dirt smudge 19.96%.", C),
        Fact(g, "Socks, weeds, wrappers and smudges together lower happiness at 10 and at 20; a clean house (0) "
                "or 1 to 4 raises it.", C),
        Fact(g, upgrade("Maid", "$1,000", f"every game hour ({game_text(3_600)}), in the daytime only (the game's "
                                          "day, which follows your PC's clock), every sock, candy wrapper, cobweb "
                                          "and dirt smudge is removed; a visit that falls at night is skipped."), E),
        Fact(g, upgrade("Gardener", "$1,000", "every game hour (game time, as the Maid), in the daytime only, every "
                                              "weed in the yard is removed."), E),
        Fact(g, "The kitchen garbage is full at 20.", C),
        Fact(g, f"The blue sock vanishes as soon as it appears: a sock is one of six sock pictures ({_odds(0, 6)} "
                "for the blue one), and the blue one's number is also the last collectible-type number, so the "
                "frame check (real time) that removes collectibles whose 2 minutes of real time are up reads its time "
                "as well; a mess never sets that time, so the check removes the blue sock at the next frame.", C),
        Fact(g, "Virtual Families 2's ants, the laundry-room sock pile and its house-renovation messes: "
                + NOT_IN_VF1 + ".", C),
    ]


def _collectibles() -> list[Fact]:
    g, E, C, U = COLLECTIBLES, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "A collectible may appear every frame with the code's 3 in 6,600 roll, exactly 15 in 32,768 "
                "(0.0458%). Frames run on real time, so this is the same at any speed; none while paused.", C),
        Fact(g, upgrade("Lucky Rock", "$77,777", "a 3 in 3,300 roll, exactly 30 in 32,768 (0.0916%) a frame "
                                                 "(real time), so twice as often."), E, sub=True),
        Fact(g, "In real time: the game paces its frames at 30 a second (each frame waits out the rest of 1,000 / 30 "
                "= 33 milliseconds), so while the PC keeps up there are 30 rolls a second of real time and a "
                "collectible appears on average every 73 seconds of real time (every 36 with the Lucky Rock); a PC "
                "that cannot keep up draws fewer frames and so fewer rolls.", C),
        Fact(g, "At most two collectibles are out at once (two places); with both taken nothing new appears, except "
                "the “Oh! A collectible!” e-mail's rare one, which always goes in the first place, "
                "replacing whatever lies there.", C, sub=True),
        Fact(g, "Rarity: rare 4.00%, uncommon 13.01%, common 82.98%. Nothing appears if that item is already "
                "out or being carried, or (photo pieces) already owned.", C),
        Fact(g, upgrade("Lucky Rock", "$77,777", "rare 8.01%, uncommon 26.03%, common 65.97%."), E, sub=True),
        Fact(g, "Where: each roll picks one of 23 spawn areas on the house map (1 in 23 each: 1,425 or 1,424 "
                "of rand's 32,768 values), and a random walkable spot inside it. An area of the Picture Pieces is "
                "picked again until another area comes while the shed has not been opened; an area of the Bugs "
                "likewise while the sky is not Raining or Stormy. Then the item is one of its collection's four "
                "of the rolled rarity (25.00% each).", C),
        *[Fact(g, text, C, sub=True) for text in _collection_areas()],
        Fact(g, "How long one lasts: 2 minutes of real time on the ground (120 seconds on the save's real-time "
                "clock, the PC's clock less the family's start, set when it appears). That clock does not stop "
                "while paused and counts the time the game is closed, so a collectible on the ground when the game "
                "is closed is gone when it is loaded more than 2 minutes later. A family member dropped on it "
                "starts Found a new item and carries it to the collection.", C),
        Fact(g, "Collecting: the first of each item goes into its collection and counts toward that collection's "
                "trophy (12 needed). A second one of an item already collected is sold online at once: $5 common, "
                "$15 uncommon, $50 rare, counted as earnings and toward the Recycler, Monetizer and Seller "
                "trophies.", C),
        Fact(g, "The full-set reward: no money and no item. A full collection of 12 wins its trophy (Bugs: "
                "Entomologist; Old Coins: Numismatist; Nuts and Twigs: Botanist; Picture Pieces: Photo finish), "
                "and all four win Master collector; those count toward Trophy collector (all 11 collecting "
                "trophies). The hall cabinet shows “Collectibles Found:” of 48.", C),
        Fact(g, "Each of the 48 collectibles (the game gives them no names of their own, only their collection, "
                "rarity and picture), with its chance per appearance; the first figure is with the shed open and "
                "rain falling, the second with neither (only Old Coins and Nuts and Twigs can come then):", C),
        *[Fact(g, text, C, sub=True) for text in _collectible_items()],
        Fact(g, "Virtual Families 2's collection page of fossils and the Rockhound Certificate that opens their "
                "areas: " + NOT_IN_VF1 + ".", C),
    ]


# The collectible spawn areas: CCollectableItem's new-game set-up 0x414370 run as linked (p_carea.py): x0, y0, x1,
# y1 on the house map (pixels) and the collection; the picker 0x414A20 rolls GetRandom(23) over them in this order.
_AREAS = (
    ("Nuts and Twigs", (1307, 80, 1717, 199)), ("Nuts and Twigs", (1439, 200, 1931, 294)),
    ("Nuts and Twigs", (1619, 294, 1931, 520)),
    *[("Picture Pieces", (124, 125, 867, 651))] * 4,
    ("Bugs", (1551, 407, 1873, 679)), ("Bugs", (1551, 407, 1873, 679)), ("Bugs", (1325, 1253, 1506, 1422)),
    ("Bugs", (116, 208, 305, 896)), ("Bugs", (116, 208, 305, 896)),
    ("Old Coins", (415, 1403, 543, 1609)), ("Old Coins", (505, 1564, 705, 1700)), ("Old Coins", (745, 1720, 1539, 1818)),
    ("Old Coins", (1539, 1779, 1677, 1871)), ("Old Coins", (415, 1403, 543, 1609)), ("Old Coins", (505, 1564, 705, 1700)),
    ("Old Coins", (658, 1656, 854, 1750)), ("Old Coins", (1439, 1343, 1563, 1429)), ("Old Coins", (1672, 1203, 1738, 1261)),
    ("Old Coins", (1725, 1140, 1793, 1198)), ("Old Coins", (1572, 308, 1672, 428)),
)
_COLLECTIONS = ("Old Coins", "Nuts and Twigs", "Bugs", "Picture Pieces")


def _area_weights(open_shed: bool, raining: bool) -> dict[str, float]:
    """Each collection's share of the appearances: its areas' GetRandom(23) counts, the re-picked ones left out."""
    w = {name: 0 for name in _COLLECTIONS}
    for k, (name, _) in enumerate(_AREAS):
        if (name == "Picture Pieces" and not open_shed) or (name == "Bugs" and not raining):
            continue
        w[name] += _below(23, k + 1) - _below(23, k)
    total = sum(w.values())
    return {name: n / total for name, n in w.items()}


def _collection_areas() -> list[str]:
    out = []
    share = _area_weights(True, True)
    for name in _COLLECTIONS:
        rects = [r for n, r in _AREAS if n == name]
        where = "; ".join(f"x {x0:,} to {x1:,}, y {y0:,} to {y1:,}"
                          + (f" (counted {rects.count((x0, y0, x1, y1))} times)"
                             if rects.count((x0, y0, x1, y1)) > 1 else "")
                          for x0, y0, x1, y1 in dict.fromkeys(rects))
        cond = {"Bugs": ", only while the sky is Raining or Stormy",
                "Picture Pieces": ", only once the shed has been opened, and a piece already found never comes "
                                  "again"}.get(name, "")
        out.append(f"{name}: {len(rects)} of the 23 areas ({100 * share[name]:.2f}% of the appearances with every "
                   f"area open{cond}): {where} (house-map pixels).")
    return out


def _collectible_items() -> list[str]:
    hits = {"common": 32768 - _below(100, 17), "uncommon": _below(100, 17) - _below(100, 4),
            "rare": _below(100, 4)}
    both, neither = _area_weights(True, True), _area_weights(False, False)
    out = []
    for name in _COLLECTIONS:
        for rarity in ("common", "uncommon", "rare"):
            for k in range(1, 5):
                p1 = both[name] * hits[rarity] / 32768 / 4
                p2 = neither[name] * hits[rarity] / 32768 / 4
                out.append(f"{name}, {rarity} {k}: {100 * p1:.3f}% / {100 * p2:.3f}%.")
    return out


def _malfunctions() -> list[Fact]:
    g, E, U = MALFUNCTIONS, VERIFIED_E, UNCONFIRMED
    return [
        Fact(g, "Every 2 seconds of real time, at any speed and also while the game is paused, a house malfunction "
                "has a 1 in 800 chance (exactly 41 in 32,768): on average one every 26.6 minutes of real time "
                "while the game is open.", E),
        Fact(g, "Only when no malfunction is already happening; then one of 8 is picked at random, and none "
                "happens if that one's permanent fix has been bought.", E),
        Fact(g, "A malfunction's permanent fix is set when a family member repairs that malfunction while the family "
                "owns A Box of Tools and Parts (see Home Improvements); without it a repair only ends the "
                "malfunction.", VERIFIED_C, sub=True),
        Fact(g, "The eight, by the action that fixes each (the fix switches that malfunction off) and the alarm the "
                "family raises: the router (“There is no Internet!”; Fixing the router), the toilet "
                "(“The toilet is clogged!”; Fixing the blocked toilet), the shower (“The shower is "
                "clogged!”; Fixing the shower), three leaking sinks (“The kitchen sink is leaking!” "
                "and “The bathroom sink is leaking!”; Fixing the leaky sink, one action for each sink), "
                "an oven fire (“There is an oven fire!”; Putting out a stove fire) and a dryer lint "
                "fire (“The dryer lint is burning!”; Putting out the laundry fire). The Water Pressure "
                "Surge pop-up's five leaks are the three sinks, the toilet and the shower.", VERIFIED_C),
        Fact(g, "Virtual Families 2's 14-way pick, its ants and the north bathroom's leaks: " + NOT_IN_VF1 + ".",
             VERIFIED_C),
    ]


# ---------------------------------------------------------------------------
# The store: every item it sells, the home improvements, the career rooms, and the patcher's purchases.
# Prices, doses and stock are the exe's item table (0x4FE1B0 + 32 x (item - 1): +4 stock, +8 doses, +0xC price,
# +0x10 name; spec section 23), the career rooms' prices the CTech table 0x4EF620. Effects: the drop handler
# 0x4462C0 and UseItemOnFamilyMember 0x442B30 (emulated, t_items.py / t_items2.py, every roll forced to its lowest
# and highest value), the plan steps they queue (ProcessCurrentPlan 0x48E350, read), the happiness update 0x48FF30
# (house upgrades and likes), theStoreScene::Buy 0x449A70 and the specials draw 0x449480. The patcher's pages:
# vf1fun.dll's own dialog procedures (CheatsProc, VillagerCheatsProc) emulated with the game (t_cheats.py), the
# rest read in its source on the Upgrades menu's path.
# ---------------------------------------------------------------------------

# item -> (name, price) as the exe's item table holds them (tests pin these to the exe)
ITEMS = {
    1: ("Praising Glove", 0), 2: ("Scolding Glove", 0), 3: ("Ball", 10),
    4: ("Groceries: Grains", 20), 5: ("Groceries: Dairy", 30), 6: ("Groceries: Meats", 70),
    7: ("Groceries: Fruits and Veggies", 40), 8: ("Organics: Grains", 40), 9: ("Organics: Dairy", 70),
    10: ("Organics: Meats", 160), 11: ("Organics: Fruits and Veggies", 110), 12: ("Energy Drink", 15),
    13: ("Chamomile Drink", 10), 14: ("Mega Chamomile Extract", 10), 15: ("Delicious Candy", 7),
    16: ("Salty Candy", 10), 17: ("Blood Orange", 10), 18: ("Male Outfit", 225), 19: ("Female Outfit", 225),
    20: ("Throat Lozenges", 5), 21: ("Peptic Syrup", 7), 22: ("Anti-inflammatory Pill", 5),
    23: ("Antitussive Syrup", 7), 24: ("Cortisone Cream", 4), 25: ("Antihistamine", 5), 26: ("Penicillin", 45),
    27: ("Vancomycin", 75), 28: ("Baby Boost", 500), 29: ("Doctor Consultation", 175), 30: ("Sweet Mango", 10),
    31: ("Perfect Bananas", 10), 32: ("Virtuoso Fragrance for Men", 25), 33: ("Virtuosa Perfume for Women", 25),
    34: ("Multivitamins", 9), 35: ("Antibacterial hand gel", 6), 36: ("Sunscreen", 12), 37: ("Towelette", 10),
    38: ("Natural Fruit Candy", 10), 39: ("Licorice Candy", 10), 40: ("Mint Candy", 10), 41: ("Cinnamon Candy", 10),
    42: ("Wood Furniture Repair Kit", 50), 43: ("Wall Repair Compound", 40), 44: ("Floor Repair Kit", 45),
    45: ("Waterproof Tape", 35), 46: ("Fountain Pump", 85), 47: ("Anti-spam Software", 125),
    48: ("Kitchen Profession Magazine", 25), 49: ("Office Profession Magazine", 25),
    50: ("Workshop Profession Magazine", 25), 51: ("Turtle Adventures", 15), 52: ("Little Man Under the Sea", 15),
    53: ("Pluto, the Loneliest Planet", 15), 54: ("Imported Candy", 25), 55: ("Bottled Tropical Rain", 18),
    56: ("Bottled Tropical Sunshine", 18), 57: ("Desensitization Kit", 75), 58: ("Encyclopedia", 75),
    59: ("Weed Bomb", 65), 60: ("Magic Barker and the Loose Screw", 24), 61: ("Pet Cat", 500), 62: ("Pet Dog", 500),
    63: ("Pet Turtle", 500), 64: ("Male Outfit", 100), 65: ("Female Outfit", 100), 66: ("Flat Screen TV", 2400),
    67: ("Collection of Paintings", 550), 68: ("Air Purifier", 250), 69: ("A Box of Tools and Parts", 1200),
    70: ("Sheets and Pillows", 350), 71: ("Fish Tank", 850), 72: ("Bathroom Upgrade", 100), 73: ("Treadmill", 3400),
    74: ("Radio and MP3 Player", 250), 75: ("Pinball Machine", 4500), 76: ("Patio Furniture", 1650),
    77: ("Swimming Pool", 1600), 78: ("Hammock", 700), 79: ("Outdoor Barbecue Grill", 850), 80: ("Birdhouse", 225),
}
CAREER_ROOM_PRICES = (0, 5000, 15000)        # CTech::GetPrice(room, level 1 / 2 / 3), the same for all three rooms
# The specials refresh 0x496D80 compares GetSecondsFromGameStart 0x4036D0 (time() since the start: REAL seconds,
# not the game clock) with its due time and sets it to now + 0x3840, so the specials change every 4 real hours at
# any game speed, also counting paused and closed time.  It runs only when the store page opens (the store scene's
# activation 0x4498C0 calls 0x496C70, 0x496CD0 and 0x496D80, their only callers there), so a draw comes at the
# first opening after its time; the half-price grocery 0x496CD0 is the same on the game clock 0x422320.
SPECIALS_REAL_SECONDS = 0x3840
SPECIALS_REAL = (f"{duration(SPECIALS_REAL_SECONDS)} real time (at any game speed, also while paused and while the "
                 "game is closed)")
SALE_GAME_SECONDS = 0xA8C0
# The actions the game registers: 0x480260 calls the registrars 0x452470 (306 times) and 0x452490 (10 times),
# 316 in all (tests/test_game_mechanics.py counts them in the exe).
REGISTERED_ACTIONS = 316
PRICE_MULTIPLIERS = (2, 5, 100)             # the patcher's Store, Achievement and Collection Cheats page
CHEATS_PAGE = "the Upgrades menu's Store, Achievement and Collection Cheats page"


def money(n: int) -> str:
    return f"${n:,}"


def item(n: int, text: str, doses: str = "one use") -> str:
    """'Energy Drink ($15, one use): ...' -- the item's table name and price."""
    name, price = ITEMS[n]
    return f"{name} ({money(price)}, {doses}): {text}"


def halved(n: int) -> str:
    return money(ITEMS[n][1] // 2)


def _store() -> list[Fact]:
    g, E, C, U = STORE, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "The store sells, in fixed places, the eight grocery bags, the two outfits and ten health items "
                "(the eight medicines, Baby Boost and the Doctor Consultation); six more places hold the Flea Market (the game's code calls these items the specials), "
                "drawn at random; its Home Improvements and Career Room Upgrades pages sell the house's permanent "
                "upgrades.", C),
        Fact(g, "The price is paid when the purchase is confirmed; a purchase needs at least that much money "
                "(the bank's interest is paid first).", C),
        Fact(g, "An item goes into the item tray with its uses: one for every item, except the two gloves and the "
                "Ball, which are never used up. It works when it is dropped where it is meant to go: on a family "
                "member, in the kitchen, or on the object it is for. A repair item, the Weed Bomb or the Anti-spam "
                "Software dropped anywhere else gives \"You can't use this here!\" and stays in the tray; groceries "
                "dropped outside the kitchen give \"Groceries must be placed in the kitchen.\" and stay.", C),
        Fact(g, "Returning an unused item to the store gives back its listed price, not a sale price. Groceries "
                "can never be returned, and a used item cannot be returned (\"This item can't be returned, because "
                "it has been used!\").", C),
        Fact(g, f"The Flea Market (six places): every {SPECIALS_REAL}, the six are drawn again, at random, from the "
                "items that may appear (each Flea Market entry below says when it may), at the first opening of the "
                "store page after that time. An item cannot fill two places at once.", C),
        Fact(g, "The stock game's hidden key: a small r on the store page redraws the Flea Market and the outfit "
                "pictures once more than 1 hour of real time has passed since the last draw (see Hidden keys, "
                "clicks and cheats).", E, sub=True),
        Fact(g, with_patcher("StoreRefreshKey", "R (small or capital) on the store page redraws the store's own "
                             "Flea Market, its six random items (not the patcher's Flea Market page on the Upgrades menu), and the "
                             "outfit pictures every time, with the game's own draw; the "
                             "half-price grocery and outfits already bought stay as they are."), E, sub=True),
        Fact(g, f"On Sale: one grocery bag (organics included) at half price, drawn again at the first opening of "
                f"the store page more than {game_span(SALE_GAME_SECONDS)} after the last draw. Buying it on sale "
                "adds the price paid to the \"Coupon clipper\" trophy.", C),
        Fact(g, with_patcher("CheatUpgrades", f"{CHEATS_PAGE} multiplies every store price, the career rooms "
                             "included, by 2, 5 or 100 (rounded down after the Food Club and Health Plan discounts; at "
                             "most $2,147,483,647). Choosing the same multiplier again, or Reset, goes back to the "
                             "listed prices. Returns give back the multiplied price at the time of the return."),
             C, sub=True),
        Fact(g, with_patcher("FleaMarket", "the patcher's Flea Market page (Upgrades menu) sells every tray item except groceries "
                             "and outfits (items 12 to 17 and 20 to 63: drinks, candies, fruit, medicines, Baby Boost, "
                             "the Doctor Consultation, care items, repair items, Anti-spam Software, magazines, films, "
                             "bottles, kits, the book and the pets) at their listed price, at any time, without the "
                             "store's stock or its Flea Market draw; its Get for free button gives the item at no cost. Each "
                             "works as described below."), C),
        Fact(g, "Virtual Families 2's store tabs for furniture, renovations, services and Special Upgrades (the "
                "Lotto Ticket, the Time Warp, Adoption Services, the Maid and Gardener services), its furniture On "
                "Sale and its locks by generation: " + NOT_IN_VF1 + "; this store is one page with the items "
                "above.", C),
        Fact(g, "Virtual Families 2's six-hour Flea Market of 5 goods: " + NOT_IN_VF1 + "; here the Flea Market "
                "has six places, drawn every 4 hours of real time.", C, sub=True),
    ]


_FOOD_GROUPS = {4: "Grains", 5: "Dairy", 6: "Meats", 7: "Fruits and Veggies"}


def _store_food() -> list[Fact]:
    g, E, C = STORE_FOOD, VERIFIED_E, VERIFIED_C
    facts = [
        Fact(g, "Every bag is used by dropping it in the kitchen (anywhere else: \"Groceries must be placed in the "
                "kitchen.\"); everyone then puts the groceries away. Groceries cannot be returned.", C),
    ]
    for n in range(4, 8):
        group = _FOOD_GROUPS[n]
        facts.append(Fact(g, item(n, f"+150 food for the house, and every family member at home and alive gets the "
                                     f"{group} food group for 24 hours of real time (at any speed, also while paused "
                                     "and while the game is closed).", "one bag"), E))
    for n in range(8, 12):
        group = _FOOD_GROUPS[n - 4]
        facts.append(Fact(g, item(n, f"+250 food for the house, the {group} food group for every family member at "
                                     "home and alive for 24 hours of real time, and for each of them a happiness "
                                     "trend of +5 "
                                     "to +14 and +0 to +2 happiness.", "one bag"), E))
    facts += [
        Fact(g, "What a food group does (health, happiness, sickness and old age): see Needs and upkeep, Health, "
                "Sickness and Old age and death.", C),
        Fact(g, upgrade("Food Club", "$10,000", "every bag costs half, rounded down: groceries "
                        + ", ".join(f"{_FOOD_GROUPS[n]} {halved(n)}" for n in range(4, 8)) + "; organics "
                        + ", ".join(f"{_FOOD_GROUPS[n - 4]} {halved(n)}" for n in range(8, 12)) + "."), E, sub=True),
    ]
    return facts


def _store_meds() -> list[Fact]:
    g, E, C, U = STORE_MEDS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    later = "When they finish taking it (a step queued in their plan)"
    return [
        Fact(g, "Each medicine is one dose, dropped on one family member, and is used up whether or not it "
                "cures anything. A cure ends that symptom at once. Symptoms and infections: see Sickness.", C),
        Fact(g, item(20, "cures a sore throat. Without a sore throat it does nothing."), E),
        Fact(g, f"{later}, after a cure: -3 hunger (1 food is taken from the house) and a happiness trend of +10.",
             C, sub=True),
        Fact(g, item(21, "cures an upset stomach. Without an upset stomach: -10 energy and bathroom need +70 at "
                         "once."), E),
        Fact(g, f"{later}, after a cure: bathroom need +25 and -10 hunger (5 food is taken from the house).", C,
             sub=True),
        Fact(g, item(22, "cures a headache. Without a headache it does nothing."), E),
        Fact(g, item(23, "cures a cough. Without a cough: -20 energy at once."), E),
        Fact(g, f"{later}, after a cure: -15 energy.", C, sub=True),
        Fact(g, item(24, "cures a skin rash. Without a skin rash it does nothing."), E),
        Fact(g, item(25, "cures a blocked nose."), E),
        Fact(g, f"{later}: +5 energy, with or without a blocked nose.", C, sub=True),
        Fact(g, item(26, "ends a mild infection (the symptoms it brought stay until cured or over). Always: energy "
                         "is set to 15, bathroom need +30, and -3 health when health is above 10 (-1 below 15 "
                         "health, by the health limits). A child of 14 or younger then goes to bed."), E),
        Fact(g, item(27, "ends both a mild and a serious infection. Always: energy is set to 5, bathroom need is set "
                         "to 80, and -10 health when health is above 12 (-5 below 15 health). A child of 14 or "
                         "younger then goes to bed."), E),
        Fact(g, item(28, "on a family member with a career, fertility rises by a quarter of (102 - fertility), "
                         "rounded down, and is kept at most 100 (checked: 1 becomes 26, 40 becomes 55, 90 becomes "
                         "93), so each dose adds less. Fertility sets the chance a try for a baby works (see "
                         "Pregnancy and babies)."), E),
        Fact(g, "Baby Boost on a family member without a career: nothing happens and it stays in the tray.", C,
             sub=True),
        Fact(g, item(29, "drop it on a family member: a diagnosis e-mail arrives naming their infection (none, mild: "
                         "take Penicillin; serious: take Vancomycin), the medicine for each symptom they have, and, "
                         "for a family member with a career and fertility below 35, Baby Boost. It cures nothing."),
             C),
        Fact(g, upgrade("Health Plan", "$10,000", "the eight medicines, Baby Boost and the Doctor Consultation cost "
                        "a quarter, rounded down: " + ", ".join(f"{ITEMS[n][0]} {money(ITEMS[n][1] // 4)}"
                                                                 for n in range(20, 30)) + "."), E, sub=True),
    ]


def _store_specials() -> list[Fact]:
    g, E, C, U = STORE_SPECIALS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    praise = ("then praises what they are doing three times (each praise: that action becomes more likely, a "
              "happiness trend of +10 and a 50.05% chance of +1 happiness; see Store: other items, Praising Glove)")
    any_time = "It may appear in the Flea Market at any time."
    return [
        Fact(g, "Each Flea Market item below is dropped on one family member unless it says otherwise, and is used up. "
                "\"A happiness trend\" is the hidden trend the happiness update reads (see Needs and upkeep). "
                "Gains and losses pass through the limits on the Health page and the energy limits (a gain above "
                "80 energy is halved, a loss below 10 halved).", C),
        Fact(g, item(12, "-4 hunger, +40 to +89 energy (checked: 50 energy becomes 90 to 100; 85 becomes 100); then "
                         "15.01% \"Doing Kung Fu\", otherwise \"Exercising outdoors\". " + any_time), E),
        Fact(g, item(13, "-10 to -29 energy (checked: 85 becomes 56 to 75; 5 becomes 1); then 15.01% \"Going to "
                         "bed\", otherwise \"Taking a nap\". " + any_time), E),
        Fact(g, item(14, "-7 hunger and no change to energy; then 15.01% \"Going to bed\", otherwise \"Taking a "
                         "nap\". " + any_time), E),
        Fact(g, item(15, f"-2 hunger, +2 or +3 happiness, {praise}. " + any_time), E),
        Fact(g, item(16, "scolds what they are doing three times (each: that action becomes less likely, a happiness "
                         "trend of -10, -1 happiness, and they run away): -3 happiness and a trend of -30 in all. "
                         + any_time), E),
        Fact(g, item(17, f"-3 hunger, +2 to +6 health, +2 to +4 happiness, +2 to +6 energy, {praise}. " + any_time),
             E),
        Fact(g, item(30, f"+2 to +6 health, +2 to +6 happiness, +2 to +6 energy, -3 hunger, {praise}. " + any_time),
             E),
        Fact(g, item(31, f"+2 to +6 health, -3 hunger, +2 to +6 happiness, +2 to +6 energy, {praise}. " + any_time),
             E),
        Fact(g, item(32, "on a family member with a career: +1 to +3 happiness at once and they start "
                         "\"Celebrating marriage\". " + any_time), E),
        Fact(g, "When they finish (a queued step): a happiness trend of +35. The Matriarch or the Patriarch (the code "
                "picks one of the two by the user's sex) celebrates too. On a family member without a career they "
                "run away instead, and it is used up. Nothing in it touches fertility or the wait for a baby.", C,
             sub=True),
        Fact(g, item(33, "the same as the Virtuoso Fragrance for Men, whoever uses it. " + any_time), E),
        Fact(g, item(34, "+1 to +3 happiness, and nothing else (no health). " + any_time), E),
        Fact(g, item(35, "+1 to +3 happiness at once. " + any_time), E),
        Fact(g, "When they finish (queued steps): a happiness trend of +35 and +10 health.", C, sub=True),
        Fact(g, item(36, "+1 to +3 happiness, then \"Exercising outdoors\". " + any_time), E),
        Fact(g, f"{ITEMS[36][0]}: its queued happiness trend of +25 still comes. It is the second step of the plan, "
                "and \"Exercising outdoors\" adds its own steps after it without clearing the plan (checked: after "
                "use the plan holds the +25 trend, then the exercise, which ends with +2 health, -5 energy and a "
                "happiness trend of +3).", E, sub=True),
        Fact(g, item(37, "+1 to +3 happiness at once."), E),
        Fact(g, "When they finish (a queued step): -15 dirtiness. The store holds one Towelette: once it is bought "
                "the Flea Market never offers it again.", C, sub=True),
        Fact(g, "Natural Fruit Candy, Licorice Candy, Mint Candy and Cinnamon Candy ($10 each, one use): -2 hunger, "
                f"+2 to +4 happiness, {praise}. " + any_time, E),
        Fact(g, "Kitchen Profession Magazine, Office Profession Magazine and Workshop Profession Magazine ($25 each, "
                "one use): only for a career in that "
                "room (Kitchen: room 1, Office: room 2, Workshop: room 3; see Careers and promotion): 8 work "
                "successes at once, without pay, and +8 to +15 happiness. Each success adds its usual progress "
                "(checked: a Beginner with the room at level 1 gains 1,120 of the 3,000 a promotion needs; a "
                "Licensed one gains 40), so one magazine can promote. On anyone else: \"Confused\", and it is used "
                "up. " + any_time, E),
        Fact(g, "Turtle Adventures, Little Man Under the Sea and Pluto, the Loneliest Planet ($15 each, one use): "
                "everyone at home starts \"Watching TV\" together. " + any_time, C),
        Fact(g, "What watching TV gives: nothing to any need or stat. \"Watching TV\" takes one of six seats, turns "
                "the TV on, sits and gets up again, and none of its steps changes a need, skill or stat (checked for "
                "all nine of its forms).", E, sub=True),
        Fact(g, "A family member also chooses \"Watching TV\" on their own, also when sick, while hunger is 75 or "
                "less and energy 60 or less: three times as often when they like TV, a quarter as often when they "
                "dislike it.", C, sub=True),
        Fact(g, item(54, "one of five, 20.00% each (6,554 or 6,553 rolls in 32,768): +5 to +12 happiness; -5 "
                         "happiness and the bathroom need set to 90 (\"Nature is calling!\"); -5 happiness and they "
                         "run away; an upset stomach (a symptom, 6 to 17 hours of real time); or +20 health, both "
                         "infections "
                         "ended and every symptom cured except a blocked nose. " + any_time), E),
        Fact(g, item(55, "+1 to +3 happiness, and at once the sky turns Stormy (rain with lightning; see Weather). "
                         "Bug collectibles appear only while it is Raining or Stormy. " + any_time), C),
        Fact(g, item(56, "+1 to +3 happiness, and at once the sky turns Normal, the plain sky (the code's sky 0; see "
                         "Weather). " + any_time), C),
        Fact(g, f"How long it lasts, on the game clock (game time): the Stormy sky 392 to 751 game seconds "
                f"({game_range(392, 751)}), the Normal sky 932 to 2,431 ({game_range(932, 2_431)}). The "
                "bottle holds its sky for 30 game seconds, then sets it again with the sky's own length (Stormy 360 "
                "to 719, Normal 900 to 2,399); after Stormy comes Normal, after Normal one of Sunny, Raining and "
                "Stormy, Sunny never at night (checked, every roll at its lowest and highest). Paused, the game "
                "clock stops, so the sky does not change.", E, sub=True),
        Fact(g, "Using two bottles of weather (either kind) wins the “Weather dancer” trophy.", C,
             sub=True),
        Fact(g, "Virtual Families 2's Fog In a Bottle and Snow in a Bottle: " + NOT_IN_VF1 + ".", C, sub=True),
        Fact(g, item(57, "+1 to +3 happiness, and the dislike in the first of their three dislike places is removed; "
                         "if that place is empty nothing is removed, even when the other two hold dislikes "
                         "(checked). " + any_time), E),
        Fact(g, item(58, "+1 to +3 happiness; one of the game's first 100 likes is drawn (1.00% each: 328 or 327 "
                         "rolls in 32,768; the last seven, garbage, fixing, shopping, pinball, music, art and gophers, "
                         "can never be drawn). If "
                         "they do not already like it and one of their three like places is free, it becomes a like; "
                         "if they dislike it, the dislike is removed, even when the like could not be added "
                         "(checked). " + any_time), E),
        Fact(g, item(59, "dropped in the yard: every weed in the yard is removed. " + any_time), C),
        Fact(g, item(60, "on a family member aged 14 or older: +4 or +5 happiness. " + any_time), E),
        Fact(g, "Magic Barker and the Loose Screw, the story: the reader starts \"Telling a story\". Given to a child "
                "under 14, the code picks at random another family member at home to read, one aged 14 or older "
                "with a career who is not pregnant, or one aged 55 or older; that reader gets the +4 or +5 "
                "happiness; with nobody to pick, nobody reads. Either way every family member at home aged 14 "
                "(280 age units) or under who is not holding a seat or other place gets +5 happiness and starts "
                "\"Listening to a story\".", C, sub=True),
        Fact(g, "Neither \"Telling a story\" nor \"Listening to a story\" changes a need, skill or stat: their steps "
                "only walk, sit and play the story (checked).", E, sub=True),
        Fact(g, "Pet Cat, Pet Dog and Pet Turtle ($500 each, one use): dropped in the house, it becomes the family's "
                "pet; with a pet already, a question asks before it replaces it. The store offers each one unless "
                "the family's pet is already that animal; the Pet Turtle's check tests for the dog, so with a dog "
                "the turtle is not offered, and with a turtle it is.", E),
        Fact(g, with_patcher("FixVanillaGameBugs", "the Pet Turtle's check tests for the turtle, like the cat's and "
                             "the dog's: a family with a dog is offered the turtle, and a family with a turtle is "
                             "not."), E, sub=True),
        Fact(g, "What a pet does for the family: nothing to any need, skill or stat. There are three pets (cat, dog "
                "and turtle); the pet's own code only walks it, plays its animations and has it follow a family "
                "member, and no family member's code, action or update reads the pet. Dropping something on the "
                "pet only changes what the pet does.", C, sub=True),
        Fact(g, item(47, "dropped on the computer: everyone celebrates, and the four spam e-mails (Random Events 12 "
                         "to 15) never come again. " + any_time), C),
        Fact(g, with_patcher("CheatUpgrades", f"{CHEATS_PAGE}'s Anti-Spam Software Ownership button installs it "
                             "for free, or uninstalls it."), C, sub=True),
        Fact(g, item(43, "dropped on the damaged wall: the wall's repair can start. Offered only while the wall has "
                         "not been repaired."), C),
        Fact(g, item(44, "dropped on one of the three damaged floor spots: that spot's repair can start. Offered only "
                         "while at least one of the three has not been repaired."), C),
        Fact(g, item(45, "dropped on the leaking hose: its repair can start; a finished repair fixes the hose for "
                         "good. Offered only while the hose has not been fixed."), C),
        Fact(g, item(46, "dropped on the birdbath: its repair can start; a finished repair fixes it for good (the "
                         "birdbath trophy). Offered only while the birdbath has not been fixed."), C),
        Fact(g, "How long a repair takes once the item is in place: it is done in sessions, each started by "
                "dropping a family member aged 14 or older who is not pregnant on the spot (the floor and wall "
                "sessions are also chosen on their own). The hose needs 1 session; the birdbath 1 (\"Installing "
                "birdbath pump\": the dropped family member and a second one the code finds, who does the repair; "
                "with nobody found, nothing is repaired); a floor spot 6 (17 repair steps, 3 a session); the wall "
                "12 (2 repair steps to start it, then 24 on each of its two sides, 4 a session, the first session "
                "included) "
                "(checked, every roll at its lowest and highest). Each hose, floor and wall session also gives +2 "
                "dirtiness and a happiness trend of +10. The real time between sessions is set by the player and the "
                "family's own choices, so a repair has no fixed real length.", E, sub=True),
    ]


def _store_other() -> list[Fact]:
    g, E, C, U = STORE_OTHER, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Male Outfit and Female Outfit ($225 each in the store, one use): the outfit changes the family "
                "member's clothes (their body picture). The Male Outfit only fits a male family member (\"This "
                "outfit is for a male!\") and the Female Outfit only a female one; otherwise it stays in the tray. "
                "In the tray an outfit is a separate item listed at $100, so returning it gives back $100, not "
                "$225.", C),
        Fact(g, "Which outfit the store hands over: one clothes picture drawn for the Male Outfit and one for the "
                "Female Outfit, each 0 to 49 (1.999% or 2.002% each: 655 or 656 rolls in 32,768), drawn again when "
                f"the store page opens once more than 14,400 game seconds ({game_text(14_400)}) have passed since the "
                "last draw. Buying one keeps the picture drawn then, and every outfit of that kind in the tray shows "
                "and puts on the picture of the last one bought (checked: a Male Outfit bought at picture 7 gives 7; "
                "after a redraw to 12 it still gives 7; once a second is bought, both show and put on 12).", E,
             sub=True),
        Fact(g, with_patcher("FixVanillaGameBugs", "each outfit in the tray keeps the picture it was bought at, "
                             "also when it is moved in the tray, and putting it on gives that picture (checked: the "
                             "first Male Outfit bought at 7 still shows and puts on 7 after a second is bought at "
                             "12); an outfit bought before the fix shows and gives the last one bought, as before."),
             E, sub=True),
        Fact(g, "Praising Glove (free, in the tray from the start, never used up): drop it on a family member to "
                "praise what they are doing: that action's weight rises by a twentieth of the room left to its "
                "maximum (at least 1), so they choose it more often; a happiness trend of +10; and a 50.05% "
                "chance of +1 happiness. Praising the same action a third time in a row makes them run away "
                "instead of the trend and happiness (the weight still rises). Picking up a sock, a candy wrapper, "
                "a weed, a cobweb or a dirt smudge, running away, and eight other actions the code lists cannot be "
                "praised at all.", C),
        Fact(g, "Scolding Glove (free, in the tray from the start, never used up): drop it on a family member to "
                "scold what they are doing: that action's weight falls by a fifteenth of its distance above its "
                "minimum (at least 1); a happiness trend of -10, -1 happiness, and they run away.", C),
        Fact(g, item(42, "never offered: the Flea Market draw skips it, so in the stock game the broken chair it "
                         "repairs can never be mended. Dropped on the broken chair, its repair could start."), C),
        Fact(g, with_patcher("FleaMarket", "the patcher's Flea Market page (Upgrades menu) sells the Wood Furniture Repair Kit ($50), so the "
                             "chair can be repaired."), C, sub=True),
        Fact(g, "Ball ($10 in the item table, never used up): dropping it on a family member does nothing (the drop "
                "handler has no use for it).", C),
        Fact(g, "The store never offers the Ball: its Flea Market table lists it in the first Flea Market place, but the "
                "first opening of the store page fills all six places, with a draw, or in a new family's first 2 "
                "seconds of real time with the kept Flea Market items, empty then (checked: the Ball is gone after either); the draw "
                "never picks the Ball.", E, sub=True),
    ]


# Home Improvements: (item, like ids it rewards (names), trend for a matching like, what else it does, label)
_ACTIVITY = ("A new activity: a family member dropped on it uses it, and family members choose it on their own "
             "once it is owned.")
_HOME = (
    (66, "TV", 35, "The Rebate e-mail (Random Event 25) comes only once it is owned.", VERIFIED_C),
    (67, "art", 35, "The Delivery Truck pop-up (Random Event 57) comes only while it is not owned, and its first "
                    "choice gives it.", VERIFIED_C),
    (68, None, 0, "+1 year on the safe age for old age (see Old age and death).", VERIFIED_E),
    (69, "tools", 10, "Every malfunction a family member repairs from then on is fixed for good: the random "
                      "malfunction roll never picks it again (see Malfunctions).", VERIFIED_C),
    (70, "sleeping", 25, "Going to bed gives +15 energy more. The Wrong Address pop-up (Random Event 56) comes only "
                         "while it is not owned and gives it for $100.", VERIFIED_C),
    (71, "fish", 35, "", VERIFIED_C),
    (72, "bathing", 25, "+1 year on the safe age for old age (see Old age and death).", VERIFIED_E),
    (73, "exercising", 35, _ACTIVITY, VERIFIED_C),
    (74, "music", 35, _ACTIVITY, VERIFIED_C),
    (75, "pinball", 45, _ACTIVITY, VERIFIED_C),
    (76, "resting, sunlight or sitting", 25, _ACTIVITY, VERIFIED_C),
    (77, "swimming", 35, _ACTIVITY, VERIFIED_C),
    (78, "solitude, quiet or resting", 25, _ACTIVITY + " The An extra hammock e-mail (Random Event 21) comes only "
                                           "while it is not owned, and gives one free.", VERIFIED_C),
    (79, "BBQ or burgers", 25, _ACTIVITY + " The BBQ Party pop-up (Random Event 43) comes only once it is owned.",
     VERIFIED_C),
    (80, "birds", 35, "The Birdwatcher Society pop-up (Random Event 39) comes only once it is owned; The Rare Bird "
                      "pop-up (Random Event 70) comes only while it is not, and its first choice sells it for "
                      "$235 to $305.", VERIFIED_C),
)


def _home() -> list[Fact]:
    g, E, C, U = HOME, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    facts = [
        Fact(g, "Each of the 15 is bought once, from the store's Home Improvements page, and stays for good; "
                "everyone celebrates the purchase. Every one owned adds +10 to every family member's happiness "
                "trend at each happiness update (every 3 age units; "
                f"{units_text(3)}); a family member with a matching like gets the extra shown, once per "
                "improvement however many of the likes they have.", C),
    ]
    for n, likes, extra, more, label in _HOME:
        like = f"+{extra} more for a family member who likes {likes}." if likes else "No like bonus."
        facts.append(Fact(g, item(n, f"{like} {more}".strip(), "bought once"), label))
    facts += [
        Fact(g, with_patcher("OlderVillagerMortalityCurve", "the Air Purifier and the Bathroom Upgrade no longer "
                             "change old age."), E, sub=True),
        Fact(g, "Virtual Families 2's Home Renovation rooms and remodels: " + NOT_IN_VF1 + "; the house's rooms are "
                "fixed and these 15 improvements are its upgrades.", C),
    ]
    facts += [Fact(g, text, label, sub=sub) for text, label, sub in _ACTIVITIES]
    return facts


# What the activities give (t_beh.py: each action run as linked, its plan's steps through ProcessCurrentPlan) and
# who chooses them (t_recs.py: the action records 0x482120 writes, as the chooser 0x4886E0 tests them).
_DAY = "from sunrise until 2 hours after sunset (your PC's clock and date: real time)"
_ACTIVITIES = (
    ("What the activities give, each time: \"a happiness trend\" is the hidden trend of Needs and upkeep; "
     "\"dirtiness\" and \"the bathroom need\" rise as they get worse. Each activity is chosen only while its "
     "improvement is owned, and only " + _DAY + " unless it says otherwise.", VERIFIED_C, False),
    ("Treadmill: \"Walking on the treadmill\": +8 dirtiness and a happiness trend of +4. \"Running on the "
     "treadmill\": +6 dirtiness, a happiness trend of +2 and -8 energy.", VERIFIED_E, True),
    ("Both are for family members aged 14 or older who are not pregnant, with health 35 or more, happiness 25 or "
     "more, hunger 65 or less and energy 45 or more.", VERIFIED_C, True),
    ("Radio and MP3 Player: \"Dancing\": -4 energy, a happiness trend of +2 and +2 dirtiness. \"Listening to the "
     "radio\": a happiness trend of +4.", VERIFIED_E, True),
    ("Both are for any age. Dancing: happiness 40 or more, hunger 75 or less, energy 50 or more. Listening: also "
     "when sick, happiness 15 or more, hunger 75 or less, energy 20 or more.", VERIFIED_C, True),
    ("Pinball Machine: \"Playing pinball\": a happiness trend of +5, +1 dirtiness and -3 energy.", VERIFIED_E, True),
    ("For any age, not pregnant, with happiness 30 or more, hunger 75 or less and energy 35 or more.", VERIFIED_C,
     True),
    ("Patio Furniture: \"Enjoying the patio\" changes no need or stat. \"Studying on the patio\": -3 energy, a "
     "happiness trend of +2 and +2 hunger, or nothing on the path where its code ends before the study (the "
     "earlier reading of nothing at all was that path only).", VERIFIED_C, True),
    ("Both only while the sky is Normal (the plain sky; see Weather). Enjoying: any age, health 12 or more, hunger 75 or less, energy 65 or less. "
     "Studying: ages 14 to 18, happiness 25 or more, hunger 60 or less, energy 35 or more.", VERIFIED_C, True),
    ("Swimming Pool: \"Swimming in the pool\": +5 dirtiness, -2 energy and a happiness trend of +3. \"Splashing in "
     "the pool\": +8 dirtiness, -2 energy and a happiness trend of +10. \"Playing in the pool\": +2 hunger, -3 "
     "energy and a happiness trend of +1.", VERIFIED_E, True),
    ("All three not pregnant, with health 30 or more, happiness 40 or more, hunger 75 or less and energy 25 or "
     "more. Swimming and Playing: any age, only while the sky is Normal, hunger 5 or more. Splashing: aged 14 or "
     "under, in any sky, hunger 20 or more.", VERIFIED_C, True),
    ("Hammock: \"Relaxing in the hammock\": with nobody in the hammock, +4 dirtiness, a happiness trend of +1 and "
     "+2 energy; with someone already in it, a happiness trend of -1 and nothing else (the earlier reading of -1 "
     "only was the taken hammock).", VERIFIED_C, True),
    ("For any age, only while the sky is Normal, with happiness 25 or more, hunger 75 or less and energy 65 or "
     "less.", VERIFIED_C, True),
    ("Outdoor Barbecue Grill: \"Barbecuing!\": -7 hunger and 3 food used, +4 dirtiness, +4 bathroom need and a "
     "happiness trend of +4. \"Cleaning up BBQ\": +7 dirtiness and a happiness trend of +1.", VERIFIED_E, True),
    ("Both for family members aged 14 or older who are not pregnant, only while the sky is Normal, with health 15 or "
     "more, happiness 50 or more, hunger 45 or more and energy 35 or more. \"Eating a burger\" asks for health 300 "
     "or more and nothing else starts it, so it never happens.", VERIFIED_C, True),
    ("Collection of Paintings: the Magic Fish is one of its paintings, not in the Fish Tank. \"Admiring the Magic "
     "Fish\" and the two \"Adjusting the painting\" actions change no need or stat.", VERIFIED_E, True),
    ("All three need the Collection of Paintings and are for family members aged 18 or older with hunger 35 or "
     "less (55 or less, and happiness 10 or more, to adjust the second painting) and energy 15 or more.", VERIFIED_C, True),
    ("Fish Tank: \"Feeding the fish\": a happiness trend of +4. \"Looking at the fish\" and \"Bothering the fish\" "
     "change no need or stat.", VERIFIED_E, True),
    ("All three: any age, hunger 35 or less, energy 25 or more.", VERIFIED_C, True),
)


def _career_rooms() -> list[Fact]:
    g, E, C = CAREER_ROOMS, VERIFIED_E, VERIFIED_C
    return [
        Fact(g, "The Kitchen, the Office and the Workshop each start at level 1 (\"the standard ... that was "
                "present in your house when you moved in\"). Level 2 costs $5,000 and level 3 $15,000, for each "
                "room; level 3 needs level 2 first (\"This upgrade is not available yet!\").", C),
        Fact(g, "A room's level multiplies the progress of every work success in its careers: level 2 doubles "
                "it, level 3 triples it (successes per promotion: see Careers and promotion; Master needs none). "
                "Kitchen: careers of room 1, Office: room 2, Workshop: room 3.", E),
        Fact(g, "A family member who likes cooking (Kitchen), computers (Office) or tools (Workshop) gets a "
                "happiness trend of +500 at each happiness update with that room at level 2, +1,000 at level 3.",
             C),
        Fact(g, with_patcher("CheatUpgrades", f"{CHEATS_PAGE}'s 2x, 5x and 100x prices multiply these too "
                             "($10,000 / $30,000 at 2x)."), C, sub=True),
    ]


def _patcher_special() -> list[Fact]:
    g, E, C = PATCHER_SPECIAL, VERIFIED_E, VERIFIED_C
    return [
        Fact(g, with_patcher("SpecialUpgrades", "the Upgrades menu's Special Upgrades page sells the six purchases "
                             "below, each kept per family. Buying an owned one again removes it, with no refund, "
                             "except the Brokerage Account (below)."), C),
        Fact(g, upgrade("Brokerage Account", "$10,000", "interest 11% a game day (24 hours of game time) instead of "
                        "10%; buying it again "
                        "sets 1%, and each purchase after that adds 2 points, up to 11% (see Money and interest)."),
             E),
        Fact(g, upgrade("Food Club", "$10,000", "a delivery at once and then every game day (24 hours of game time): "
                        "+500 food and all four food groups for 24 hours of real time; a hungry family member always "
                        "finds food; every grocery bag half price (see Needs and upkeep and Store: groceries)."), E),
        Fact(g, upgrade("Health Plan", "$10,000", "the medicines, Baby Boost and the Doctor Consultation cost a "
                        "quarter (see Store: medicines)."), E),
        Fact(g, upgrade("Lucky Rock", "$77,777", "collectibles appear twice as often and are rare 8.01%, uncommon "
                        "26.03% (see Collectibles)."), E),
        Fact(g, upgrade("Maid", "$1,000", f"every game hour ({game_text(3_600)}), in the daytime, every sock, candy "
                        "wrapper, cobweb and dirt smudge is removed (see Messes)."), E),
        Fact(g, upgrade("Gardener", "$1,000", "every game hour (game time), in the daytime, every weed in the yard "
                        "is removed (see Messes)."), E),
    ]


def _patcher_menu() -> list[Fact]:
    g, E, C = PATCHER_MENU, VERIFIED_E, VERIFIED_C
    cheat = lambda text: with_patcher("CheatUpgrades", text)          # noqa: E731
    return [
        Fact(g, cheat("every page below is free and acts at once. No Money, No Food, every Villager Cheats button, "
                      "the achievement and collection buttons, Divorce Spouse and Evict Family ask first. The "
                      "Villager Cheats page acts on the family member picked in its list, or on everyone "
                      "(Everyone)."), C),
        Fact(g, cheat("Cheat Upgrades page: No Money sets $0; + 100 and + 10,000 add that much; Max sets "
                      "$4,000,000,000; Set money to $ sets any amount from 0 to 4,000,000,000. Food: No Food sets "
                      "0, + 100 and + 10,000 add that much (stopping at 2,147,483,647), Max sets 2,147,483,647, Set "
                      "food to sets any amount up to 2,147,483,647 (checked: $1,000 becomes $0, $1,100, $11,000, "
                      "$4,000,000,000 and $123,456; 500 food becomes 0, 600, 10,500, 2,147,483,647 and 777; "
                      "2,147,483,000 + 10,000 becomes 2,147,483,647)."), E),
        Fact(g, cheat("Cheat Upgrades page, Interest rate %: any rate from 1% to 11% for every family, kept in "
                      "settings.ini (checked: 12 is refused; see Money and interest)."), E),
        Fact(g, cheat("Villager Cheats page: Max health sets health 100; Max happiness and Psychotherapy set "
                      "happiness 100; Max energy sets energy 100; Fill up (Fed) sets hunger to 1 (fully fed); Cure "
                      "illnesses clears all seven symptoms and their times and ends a mild and a serious "
                      "infection, as Vancomycin does; All of these does all five (checked on a family member at 50 "
                      "health, energy and happiness and 60 hunger, with three symptoms and both infections)."), E),
        Fact(g, cheat("Villager Cheats page: Instant job promotion promotes a family member with a career one level "
                      "at once, without pay, as the Professional Career Training pop-up does (checked: Beginner to "
                      "Novice); Career Change draws a new career at random and starts it at Beginner. Neither works "
                      "on a family member without a career (\"Only adults with a career can do that.\")."), E),
        Fact(g, cheat("Villager Cheats page: Systematic Desens. removes the dislike in the first filled dislike "
                      "place (checked: with dislikes in the first two places, the first is removed)."), E),
        Fact(g, cheat("Villager Cheats page: Higher Learning adds a like drawn at random that they neither like "
                      "nor dislike, into a free like place (\"Every like slot is already full.\" when none is "
                      "free); Add Running Like adds the like for running and removes a dislike of running."), C,
             sub=True),
        Fact(g, cheat("Villager Cheats page: Set Age to 18 sets the picked family member's age to 18 years (360 "
                      "age units; checked: 30 becomes 18), for one family member only (Everyone is refused); "
                      "Boarding School refuses a family member with a career (checked)."), E),
        Fact(g, cheat("Villager Cheats page: Boarding School sends a child (no career) away from home the way the "
                      "age-19 departure does (\"is going to college\"; see Leaving home)."), C, sub=True),
        Fact(g, cheat("Villager Cheats page, Change Appearance: Change (0-49) sets the head (face and hair) and body "
                      "(clothes) pictures to the numbers typed, each 0 to 49 (checked: 7 and 9 set; 50 refused)."),
             E),
        Fact(g, cheat("Villager Cheats page: Random look draws both pictures at random (0 to 49 each); the "
                      "Clothing and Hairstyles page sets one by clicking it; the family tree portrait follows."), C,
             sub=True),
        Fact(g, cheat("Store, Achievement and Collection Cheats page: 2x, 5x and 100x Prices and Reset (see Store "
                      "rules); Complete all Achievements and Reset Achievements (the game's trophies); "
                      "Complete all collections and Reset all collections (the collectible albums); Anti-Spam "
                      "Software Ownership (see Store: Flea Market)."), C),
        Fact(g, cheat("House and Yard page: fills the free mess places in the house with trash (5 dirt smudges, 5 "
                      "socks, 5 candy wrappers) or the yard with up to 15 weeds; Clean House removes every sock, "
                      "candy wrapper, cobweb and dirt smudge; Clean Garden every weed; it can also start all eight "
                      "malfunctions at once or end every active one (see Messes and Malfunctions)."), C),
        Fact(g, cheat("Time Controls page: Pause, Resume, Slow, Normal, Fast, 5x and 10x, and Time Warp: +3 years "
                      "(see Time and ageing)."), C),
        Fact(g, cheat("Family: Marriage, Babies and Adoption page: Enable Same-Sex Marriage and Allow Reroll of Marriage Candidates (kept per "
                      "family); Force Marriage Email; Divorce Spouse (removes the spouse from the house and the "
                      "family tree for good); the next pregnancy's sex (either, male, female) and number (any, "
                      "single, twins, triplets), and Force Successful Pregnancy, each kept until a pregnancy "
                      "succeeds; Spawn Male / Female Child and Adopt Outside Boy / Girl (age 2 to 13, an optional "
                      "name); Adopt New Person after the family is lost; Evict Family (a new family, keeping the "
                      "money, the house and everything owned)."), C),
        Fact(g, with_patcher("FleaMarket", "the patcher's Flea Market page: see Store rules."), C),
        Fact(g, with_patcher("RollTheDice", "Roll the Dice: $500 for a Popup Event at once (see Random Events)."),
             C),
        Fact(g, cheat("Patcher Achievements page: 12 milestones the patcher records per family (ages 70, 80, 90, "
                      "100 and over 122, four rare head pictures in the family tree, the most money, the most food, "
                      "and all of them). They are records only: they give nothing."), C),
    ]


_CLOSED = "also while paused and while the game is closed"
_TIMERS = (
    ("Family update", "every 2 seconds of real time, at any speed, also while paused", VERIFIED_C),
    ("Age unit", units_text(1), VERIFIED_E),
    ("Pregnancy", "21 age units, " + units_text(21), VERIFIED_E),
    ("Body removed", "240 age units, " + units_text(240), VERIFIED_E),
    ("Wait between babies", f"10 minutes to 4 hours 10 minutes of real time, {_CLOSED}; 20 minutes after a failed "
                            "try", VERIFIED_C),
    ("Symptom", f"6 to 17 hours of real time, {_CLOSED}", VERIFIED_E),
    ("Food group", f"24 hours of real time, {_CLOSED}", VERIFIED_C),
    ("Interest", game_text(86_400) + ", every missed game day paid", VERIFIED_E),
    ("Event check", game_text(3_600) + "; the first " + game_text(900), VERIFIED_C),
    ("Dating e-mail", game_text(180) + " for the first", VERIFIED_C),
    ("Mess", game_text(18_000) + "; half that with 4 or more", VERIFIED_C),
    ("Store Flea Market", SPECIALS_REAL + ", drawn when the store page opens", VERIFIED_C),
    ("Half-price grocery", game_text(SALE_GAME_SECONDS) + ", drawn when the store page opens", VERIFIED_C),
    ("Collectible", "15 in 32,768 each frame (real time: frames are not slowed by the game speed); none while "
                    "paused", VERIFIED_C),
    ("House malfunction", "1 in 800 every 2 seconds of real time, also while paused", VERIFIED_E),
    ("Autosave", "every 10 minutes of real time, also while paused, to the same save file a quit writes",
     VERIFIED_E),
    ("Day and night", "your PC's clock (real time)", VERIFIED_C),
)


def _index() -> list[Fact]:
    g, E, C, U = INDEX, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    patched = {   # timers the patcher adds or changes, after the stock timer they sit beside
        "Collectible": [upgrade("Lucky Rock", "$77,777", "Collectible: 30 in 32,768 each frame (real time).")],
        "Mess": [upgrade("Maid", "$1,000", f"Maid's visit: {game_text(3_600)}, daytime only."),
                 upgrade("Gardener", "$1,000", f"Gardener's visit: {game_text(3_600)}, daytime only.")],
        "Wait between babies": [f"{PATCHER_PREFIX}: none after a failed try with a parent of 50 or older "
                                f"({setting('AllowOlderPregnancies')}) or a couple that cannot have a baby "
                                f"({setting('PrivateRomanticTime')})."],
        "Autosave": [(f"{PATCHER_PREFIX}: also a save right after you adopt ({setting('FixVanillaGameBugs')}); "
                      "the autosave every 10 minutes of real time is unchanged.", C)],
        "Interest": [upgrade("Food Club", "$10,000", f"Food Club delivery: {game_text(86_400)}, every missed "
                                                     "game day delivered.")],
    }
    facts = [Fact(g, "Timers, each on its clock (real time, game time or age units; game time with its real time "
                     "on Normal, Slow and Fast):", C)]
    for name, length, label in _TIMERS:
        facts.append(Fact(g, f"{name}: {length}.", label, sub=True))
        facts += [Fact(g, *(item if isinstance(item, tuple) else (item, E)), sub=True)
                  for item in patched.get(name, ())]
    facts += [
        Fact(g, "The game has 5,088 places that roll a random number; 5,087 are in code the game reaches. The gameplay ones are on "
                "this page: hunger, eating, waste, starvation, sickness, recovery, old age, conception, twins, "
                "careers, work, events, the dating candidate, messes, collectibles and malfunctions.", C),
        Fact(g, f"4,492 of them are in the family members' {REGISTERED_ACTIONS} actions and pick how long a step "
                "lasts, which variant, where they walk, and the few ranges listed in Actions (for example Taking a nap's "
                "+7 to +11 energy). What each action gives is in Actions.", C),
        Fact(g, "The rest are setup, looks, names, the screen and input. The two largest groups: the 58 rolls of "
                "the item use (see the Store groups, which give each item's ranges) and the 57 of the house's "
                "per-frame effects (frames run on real time), which pick where and when a drip, spark or puff is "
                "drawn and change nothing else.", C),
    ]
    return facts


# ---------------------------------------------------------------------------
# The groups Virtual Families 2's page has (research 2026-10-27 in C:\vf1\gm_research and the session's p_*.py
# scripts; every address is VF1's own).
# ---------------------------------------------------------------------------

# The sky: CWeather at 0x8352A4 (no RTTI; the engine's CWeather / CSunBeam 0x834D98 / CRain 0x831D90 / CLightning
# 0x8316EC, matched to VF2's B200 objects by their Reset signatures). Update 0x492420 (every frame, from 0x445660),
# set 0x492280, force 0x4921B0, start 0x4923B0 (from the game start / load 0x424110), PC-minute pick 0x492230. The
# action records' sky test is villager + id * 0xC8 + 0x2C40 (t_recs.py).
WEATHER_NAMES = ("Normal", "Sunny", "Raining", "Stormy")


def _weather() -> list[Fact]:
    g, C = WEATHER, VERIFIED_C
    return [
        Fact(g, "The sky has four states, named as the owner names them: Normal (the code's sky 0: the plain sky, "
                "nothing drawn over the house), Sunny (sky 1: the sun-beam effect, a grey tint with sun beams), "
                "Raining (sky 2: rain) and Stormy (sky 3: rain with lightning).", C),
        Fact(g, f"Normal lasts 900 to 2,399 game seconds ({game_range(900, 2_399)}); Sunny, Raining and Stormy 360 "
                f"to 719 ({game_range(360, 719)}), each length drawn evenly. All of it is game time: paused, the sky "
                "stands still.", C),
        Fact(g, "After Sunny, Raining or Stormy the sky always goes back to Normal. After Normal the next is "
                "Sunny, Raining or Stormy, 1 in 3 each by day; at night (your PC's clock) Sunny is never picked, so "
                "it is Raining or Stormy, 1 in 2 each.", C),
        Fact(g, "The sky is not saved. Each time a family starts or is loaded it begins Normal; then with a "
                f"{_below_pct(100, 20)} chance it changes 30 seconds of game time later to the sky your PC clock's "
                "minute gives (the minute's remainder after dividing by 4: 1 Sunny, 2 Raining, 3 Stormy, and 0 "
                "Sunny as well); otherwise it stays Normal for a full Normal spell.", C),
        Fact(g, "A new family's \u201cDo you need help?\u201d question at the start sets the sky Sunny.", C, sub=True),
        Fact(g, "Rain wets the yard: from the start of Raining or Stormy the wetness rises by 0.83 a game second (at "
                "most 100), and in Normal or Sunny it falls by 0.42 a game second. Once it is over 30 (after 36 game "
                "seconds of rain, all of it game time), family members who are Chillaxing, Not feeling well or Caring for baby stop and "
                "start Getting out of the rain. When a Raining or Stormy spell ends, everyone Drinking rain, Getting "
                "out of the rain or Playing in puddles stops.", C),
        Fact(g, "What the sky allows: Playing in the rain and Watching the rain only while it is Raining (not "
                "Stormy); Enjoying the patio, Studying on the patio, Swimming and Playing in the pool, Relaxing in "
                "the hammock, Barbecuing! and Cleaning up BBQ only while it is Normal; Bug collectibles only while "
                "it is Raining or Stormy.", C),
        Fact(g, "What changes it: Bottled Tropical Rain (Stormy) and Bottled Tropical Sunshine (Normal), see Store: "
                "Flea Market; the My Weather Machine e-mail (Raining), see Random Events.", C),
        Fact(g, "Virtual Families 2's Foggy and Snowing skies: " + NOT_IN_VF1 + ".", C),
    ]


# Family-member drops on the house: the drop table at 0x8754C8 (built by its CRT constructor 0x495760, run as linked:
# p_drop.py), indexed by the content-map object under the drop (Assets\cmap.dat bits 18..24, 0x4928F0 at the drop
# point 10 pixels up), called from the drop 0x4413B0 -> 0x441020 -> 0x493FB0.
_DROPS = (
    ("the hammock", "Relaxing in the hammock"),
    ("the workshop", "Fixing the leaky sink (one of the three sink fixes), Playing in the workshop, Working on "
                     "career or Shaking head"),
    ("the washer and dryer", "Doing laundry"),
    ("the treadmill's place", "Walking on the treadmill, Shaking head or Taking a nap"),
    ("the toilet", "Fixing the blocked toilet, Nature is calling! or Shaking head"),
    ("the bathroom sinks", "Getting a drink of water, Brushing teeth, Brushing hair, Flossing, Washing hair, "
                           "Admiring self or Applying deodorant"),
    ("the shower", "Taking a shower or Shaking head"),
    ("the kitchen table", "Putting away the groceries, Sitting down to a meal, Preparing a meal or Shaking head"),
    ("the kitchen trash can", "Taking the garbage out or Confused"),
    ("the stove and counter", "Working on career, Preparing a meal, Looking for snacks or Shaking head"),
    ("the TV wall", "Watching TV"),
    ("the sandbox", "Playing in the sand"),
    ("the office desk", "Fixing the router, Working on career, Browsing Web, Shaking head, or an action with no "
                        "caption of its own"),
    ("the reading seat", "Reading a magazine"),
    ("the pool", "Swimming in the pool, Playing in the pool or Running away"),
    ("the patio", "Enjoying the patio"),
    ("the refrigerator", "Looking for snacks"),
    ("the pinball corner", "Playing pinball"),
    ("the radio's end table", "Dancing or Listening to the radio"),
    ("the kitchen sink", "Doing the dishes, Working on career, Looking for snacks, Getting a drink or Shaking head"),
    ("the office toys", "Playing office"),
    ("the router", "Fixing the router"),
    ("the barbecue grill", "Barbecuing! or Shaking head"),
    ("the adults' bed", "Making the bed or Going to bed"),
    ("the children's beds", "Going to bed or Making the children's beds"),
    ("the toys", "Playing with toys"),
    ("the study desk", "Studying (Doing homework)"),
    ("the two flower boxes", "Watering the flowers"),
    ("the damaged workshop wall", "Repairing the workshop wall or Confused"),
    ("the workshop wall's other side", "Repairing the workshop wall (also \u201cWall compound has hardened!\u201d), "
                                       "for a family member aged 14 or older who is not pregnant"),
    ("the leaking hose", "Taping the leaky hose or Confused"),
    ("the birdbath", "Admiring the bird bath., Installing birdbath pump or Confused"),
    ("the three damaged floor spots", "Repairing the floor (each spot its own) or Shaking head"),
    ("the bathroom fixtures' spot", "Fixing the blocked toilet or Fixing the shower"),
    ("the fire spot", "Putting out the laundry fire or Putting out a stove fire"),
    ("two more spots", "Confused"),
    ("the blender and the mixer (in the kitchen)", "no action: with the Kitchen at level 2 or 3 the message bar says "
                                                   "\u201c... sees the blender.\u201d or \u201c... sees the "
                                                   "mixer.\u201d"),
    ("the birdhouse's place", "no new action: with the Birdhouse owned the family member walks to it"),
)


def _drops() -> list[Fact]:
    g, C = DROPS, VERIFIED_C
    return [
        Fact(g, "Dropping a family member: the game first checks for a mess or a collectible under them (a sock, "
                "wrapper, weed, cobweb or dirt smudge starts its clean-up action; a collectible starts Found a new "
                "item), then for a house object, then for another family member (see Pregnancy and babies for "
                "the try for a baby).", C),
        Fact(g, "A house object is found by the game's content map (Assets\\cmap.dat) at the drop point; each object "
                "has its own drop code, which checks the family member and the house (age, career, owned "
                "improvements, a malfunction under way, a free place) and starts one action, or none. The objects "
                "and the actions their code can start (the code's checks pick which; what each action gives: see "
                "Actions):", C),
        *[Fact(g, f"{place}: {acts}.", C, sub=True) for place, acts in _DROPS],
        Fact(g, "The TV remote and the shed door are not in this table: their own code handles a drop on them "
                "(see Hidden keys, clicks and cheats).", C, sub=True),
        Fact(g, "DEAD (never runs): one more drop code, Running away (50.05%) for a family member with one "
                "particular dislike, belongs to an object that no place on the content map carries, so no drop "
                "reaches it.", C, sub=True),
        Fact(g, "Pets are not house objects: dropping a family member on the pet starts nothing.", C, sub=True),
        Fact(g, "Virtual Families 2's furniture (bought, placed from storage, up to 30 pieces giving mood points, "
                "with drop actions on each piece's placement map): " + NOT_IN_VF1 + "; its house objects are "
                "fixed.", C),
    ]


def _pets() -> list[Fact]:
    g, E, C = PETS, VERIFIED_E, VERIFIED_C
    return [
        Fact(g, "Three pets: Pet Cat, Pet Dog and Pet Turtle, $500 each, sold in the store's Flea Market (one use "
                "each).", C),
        Fact(g, "Dropped in the house the item becomes the family's pet; the family has at most one, and with a pet "
                "already a question asks before the new one replaces it.", E, sub=True),
        Fact(g, "When the Flea Market offers each: the cat unless the pet is a cat, the dog unless the pet is a dog; "
                "the turtle's check tests for the dog, so with a dog the turtle is not offered and with a turtle it "
                "is.", E, sub=True),
        Fact(g, with_patcher("FixVanillaGameBugs", "the turtle's check tests for the turtle."), E, sub=True),
        Fact(g, "What a pet does for the family: nothing to any need, skill or stat; its own code walks it, plays "
                "its animations and has it follow a family member, and nothing in a family member's code reads it. "
                "Dropping something on the pet only changes what the pet does; dropping a family member on it "
                "starts nothing.", C),
        Fact(g, "Virtual Families 2's Pets tab (12 pets, 14 with its patcher), the Food and Water Bowls, Petting "
                "the pet and the pets' generation locks: " + NOT_IN_VF1 + ".", C),
    ]


def _clothing() -> list[Fact]:
    g, E, C = CLOTHING, VERIFIED_E, VERIFIED_C
    return [
        Fact(g, "Clothes: a family member's body picture, one of 50 (0 to 49). The store sells a Male Outfit and a "
                "Female Outfit, $225 each, one use, dropped on a family member of that sex; it changes their body "
                "picture (see Store: other items for which picture and the $100 return).", C),
        Fact(g, "The pictures the store offers: one for each outfit, 0 to 49 at random (1.999% or 2.002% each), "
                f"drawn again at the first opening of the store page more than {game_text(14_400)} after the last "
                "draw; the store's r key draws them too (see Hidden keys, clicks and cheats).", E, sub=True),
        Fact(g, "Hairstyles: part of the head picture (face and hair), one of 50, set when a family member is made "
                "and not sold anywhere in the game; from age 45 (900 age units) the game draws its older heads.", C),
        Fact(g, with_patcher("CheatUpgrades", "the Clothing and Hairstyles page sets either picture by clicking it "
                                              "(0 to 49), and the Villager Cheats page sets them by number or at "
                                              "random (see Patcher: Upgrades menu)."), C, sub=True),
        Fact(g, "Virtual Families 2's Clothing tab (Discount, Department Store and Designer outfits with their "
                "price tiers and generation locks) and its patcher's Outfit store of bodies and hairstyles: "
                + NOT_IN_VF1 + ".", C),
    ]


# The trophy table 0x4E9510 (24-byte rows: id, target, 0x77, 0, title, description; the title of row k is text
# 0x1CE + 2k), advanced by 0x413210 (id, amount) and completed by 0x413170, which also counts trophies 98 to 100 and,
# for rows 81 to 91, row 92. Every reached call was listed (p_ach.py, and p_ach40.py for the plan step 0x40).
_TROPHIES = """\
0|Gettin' paid|You earned $100.|100
1|Bring home the bacon|You earned $1,000.|1000
2|Mind on my money|You earned $10,000.|10000
3|Trump this!|You earned $100,000.|100000
4|An eventful week|You have encountered 10 email or house events.|10
5|Never a dull moment|You have encountered 50 email or house events.|50
6|Marry rich|You married someone with more than $200 in the bank.|1
7|Marry for love|You married someone with less than $75 in the bank.|1
8|A perfect match|You married someone with the same career.|1
9|Oh, baby!|You had a baby.|1
10|Oh, baby baby!|You had twins.|1
11|Ohhhhh dear...|You had triplets.|1
12|Four is enough|You had four children.|4
13|No vacancy|You had six children.|6
14|Boob tube|You praised someone who was turning off the TV.|1
15|Care and feeding|You praised someone who was making a meal.|1
16|Sleeping dragon|You praised someone who was practicing Kung Fu.|1
17|Everything in its place|You praised someone who was cleaning the nightstand.|1
18|Go-pher it!|You praised someone who was chasing gophers.|1
19|That funky smell|You praised someone who was throwing out rotten fish.|1
20|Lotta latte|You praised someone for making a latte.|1
21|1000 strokes|You praised someone who was brushing their hair.|1
22|Fire stopper|You praised someone who was putting out a smoking oven.|1
23|Praising good behavior|You praised all of the above 9 behaviors.|9
24|Praising the praiser|You praised your little people 100 times.|100
25|Sustenance|You spent $500 on food for your little people.|500
26|Abundance|You spent $1000 on food for your little people.|1000
27|Gluttony|You spent $5000 on food for your little people.|5000
28|Preparedness|You filled the kitchen with 1000 units of food.|1
29|It's not a pyramid but...|You provided all 4 food groups in a 24 hour period.|1
30|Nutrition snob|You provided all 4 food groups of organics.|1
31|Coupon clipper|You saved $500 on food by finding discounts.|500
32|A spoon full of sugar|You cured a symptom of someone who got sick.|1
33|Not just a virus|You cured a serious infection in someone.|1
34|Gravely ill|You cured a grave infection in someone.|1
35|Hic|You helped someone cure hiccups.|1
36|Fish Tycoon|You got the fish tank.|1
37|Plant Tycoon|You watered the plants in the window boxes.|1
38|Dreaming of Isola|You bought paintings for your house.|1
39|Staying cool in the pool|You have a pool.|1
40|A fun house!|You have a pinball machine.|1
41|Let's dance|You have the radio.|1
42|Time to Q|You have a barbecue grill.|1
43|Retail therapy|You bought every house upgrade.|15
44|Trick|You gave 10 pieces of nasty candy to your little friends.|10
45|Treat|You gave 10 pieces of yummy candy to your little friends.|10
46|Lucky winner|You won on a lottery scratch off.|1
47|Two thumbs up|You watched 3 movies with your family.|3
48|So like a rose|You purchased and used two perfumes.|2
49|Weather dancer|You purchased and used two bottles of weather.|2
50|Movin' on up|You got a promotion.|1
51|Office overlord|One of your little friends mastered an office career.|1
52|Cooking captain|One of your little friends mastered a kitchen career.|1
53|Workshop warrior|One of your little friends mastered a workshop career.|1
54|Building for the future|You upgraded a career room in the house.|1
55|The dream kitchen|You have a level 3 kitchen for your family to enjoy.|1
56|Office of the future|You have a level 3 office for your family to enjoy.|1
57|Workshop of wonders|You have a level 3 workshop for your family to enjoy.|1
58|Start with the basics|You repaired the floor in the house.|1
59|All the walls|You completed all of the exterior wall repairs.|1
60|The shed|You managed to open the shed.|1
61|Splish, splash!|You fixed the birdbath.|1
62|This old house|You completed all house repairs.|1
63|Sticky situation|You removed a cobweb.|1
64|Handyman|You have fixed 10 malfunctions in the house.|10
65|Sock collector|You retrieved 10 socks in the house.|10
66|The sock market|You retrieved 50 socks in the house.|50
67|A perfect sock storm|You retrieved 100 socks in the house.|100
68|Wrappers!|You disposed of 10 wrappers in the house.|10
69|Wrap attack|You disposed of 50 wrappers in the house.|50
70|The wrappers wrap-up|You disposed of 100 wrappers in the house.|100
71|See spot? Run!|You cleaned 10 dirt smudges off the floor.|10
72|Spotty behavior|You cleaned 50 dirt smudges off the floor.|50
73|Sir spot-a-lot!|You cleaned 100 dirt smudges off the floor.|100
74|Weed picker|You pulled 10 weeds from the yard.|10
75|Weed whacker|You pulled 50 weeds from the yard.|50
76|Weed obliterator|You pulled 100 weeds from the yard.|100
77|Spring cleaning|You made your house completely free of debris and dirt.|1
78|Order in the yard|You got rid of every weed in the yard.|1
79|A gleaming estate|Your home is spotless inside and out.|1
80|Where is the remote?|You helped your friends recover the remote 5 times.|5
81|Entomologist|You completed the collection of insects.|12
82|Numismatist|You completed the collection of coins.|12
83|Botanist|You completed the collection of nuts and twigs.|12
84|Photo finish|You put together the antique photo.|12
85|Master collector|You completed all 4 collections.|4
86|Recycler|You sold 5 common collectibles online.|5
87|Super recycler|You sold 15 common collectibles online.|15
88|Monetizer|You sold 5 uncommon collectibles online.|5
89|Super monetizer|You sold 15 uncommon collectibles online.|15
90|Super seller|You sold 5 rare collectibles online.|5
91|Super duper seller|You sold 15 rare collectibles online.|15
92|Trophy collector|You collected all 11 collecting trophies.|11
93|Starting out|One of your little friends achieved the age of 35.|1
94|All the wheels turning|One of your little friends achieved the age of 45.|1
95|Lessons of life|One of your little friends achieved the age of 50.|1
96|Midlife|One of your little friends achieved the age of 60.|1
97|Wise|One of your little friends achieved the age of 65.|1
98|Overachiever|You earned 10 trophies.|10
99|Unachievable|You earned 50 trophies.|50
100|The impossible dream|You earned 100 trophies!|100
"""
TROPHY_LIST = tuple((int(k), t, d, int(n)) for k, t, d, n in (row.split("|") for row in _TROPHIES.splitlines()))


def _trophies() -> list[Fact]:
    g, C = TROPHIES, VERIFIED_C
    return [
        Fact(g, f"The game has {len(TROPHY_LIST)} trophies (its Trophies screen; the code calls them "
                "achievements). Each counts toward a target and is won once the count reaches it; a trophy won "
                "stays won through every generation. A trophy gives no money and no item: winning one only "
                "counts toward Overachiever (10), Unachievable (50) and The impossible dream (100).", C),
        Fact(g, "What counts, where the code says more than the words: Gettin' paid to Trump this! count all money "
                "earned (salary, interest, paid work, event prizes and collectible sales; not a dowry or a store "
                "refund); the food trophies count the money paid for grocery and organics bags; Retail therapy "
                "counts each of the 15 Home Improvements, also those an event gives; Handyman counts each "
                "malfunction fixed; the age trophies come at the birthday in age units 700, 900, 1,000, 1,200 "
                "and 1,300 (35, 45, 50, 60 and 65 years).", C),
        Fact(g, "DEAD (never won in play): \u201cIt's not a pyramid but...\u201d. No code in the game counts toward "
                "it (every reached call of the trophy counter was listed), so only the patcher's Complete all "
                "Achievements gives it.", C),
        Fact(g, "Every trophy, with the game's words and the count it needs:", C),
        *[Fact(g, f"{title}: \u201c{desc}\u201d (needs {n:,}).", C, sub=True) for _, title, desc, n in TROPHY_LIST],
        Fact(g, with_patcher("CheatUpgrades", "Complete all Achievements and Reset Achievements on the Store, "
                                              "Achievement and Collection Cheats page; the patcher's own Patcher "
                                              "Achievements are separate records (see Patcher: Upgrades menu)."),
             C, sub=True),
        Fact(g, "The heir: when a parent with children dies and a child is still alive, the family tree offers the "
                "next generation; choosing an heir starts it and hides every other family member. See Dating, "
                "marriage and the next generation.", C),
        Fact(g, "Virtual Families 2's store locks by generation (\u201cfrom generation N\u201d): " + NOT_IN_VF1
                + "; every store item is on sale from the first generation.", C),
    ]


# Every registered action (the CRT initializer 0x480260 registers 316 behaviours): its caption (the text its code
# copies to the family member's label; two when the code picks one, for example by sex) and, for every path through
# its code, the need-change plan steps it builds (stat steps 0x2D..0x3B, the work step 0x3F and the conception step
# 0x41), from a recursive descent of the action and the action code it calls (p_paths.py, p_actblock.py).
_ACTIONS = """\
0|Caring for baby|
1|Testing bevmac chunk|
2|Going to bed|dirtiness +2 || energy +10, dirtiness +2 || energy +15, dirtiness +2
3|Filling a gopher hole|dirtiness +10, energy -3
4|Doing aerobics|energy -3, a happiness trend of +1, dirtiness +1
5|Brushing teeth|dirtiness -5
6|Playing on the lawn|
7|Going to bed|dirtiness +2, energy +5
8|Going to bed|dirtiness +2, energy +5
9|Going to bed|dirtiness +2, energy +5
10|Going to bed|dirtiness +2, energy +5
11|Going to bed|dirtiness +2, energy +5
12|Going to bed|dirtiness +2, energy +5
13|Going to bed|dirtiness +2, energy +5
14|Playing cook|
15|Playing cook|
20|Playing office|energy -2
21|Playing in the workshop|
22|Playing in the workshop|
26|Cleaning up after a meal|a happiness trend of +1, energy -2, dirtiness +4, a happiness trend of +1, energy -2, dirtiness +4
27|Doing laundry|energy -3, dirtiness +5, a happiness trend of +2
28|Doing Kung Fu|
29|Dusting furniture|
30|Feeling depressed|
31|Feeling very sick|
32|Getting a drink|
33|Sitting down to a meal|hunger -40, dirtiness +4, the bathroom need +6
34|Sitting down to a meal|hunger -40, dirtiness +4, the bathroom need +6
35|Sitting down to a meal|hunger -40, dirtiness +4, the bathroom need +6
36|Sitting down to a meal|hunger -40, dirtiness +4
37|Sitting down to a meal|hunger -40, dirtiness +4, the bathroom need +6
38|Sitting down to a meal|hunger -40, dirtiness +4, the bathroom need +6
39|Inspecting the foundation|
40|Playing with toys|
41|Digging a hole to China|dirtiness +10, energy -3, a happiness trend of +1 || dirtiness +30, energy -3, a happiness trend of +1
42|Relaxing in the hammock|dirtiness +4, a happiness trend of +1, energy +2 || a happiness trend of -1
43|Relaxing in the hammock|dirtiness +4, a happiness trend of +1, energy +2 || a happiness trend of -1
44|Looking for snacks|hunger -2, dirtiness +2, the bathroom need +3
50|Not feeling well|
51|Working on career|energy -2, a piece of career work, dirtiness +1, energy -2, hunger +1
52|Picking up a sock|dirtiness +2, a happiness trend of +10
53|Throwing away a wrapper|dirtiness +2, kitchen garbage +1, a happiness trend of +5
54|Pulling a weed|dirtiness +2, a happiness trend of +5
55|Cleaning cobwebs|a happiness trend of +10
56|Cleaning a dirt smudge|dirtiness +2, a happiness trend of +10
57|Preparing a meal|energy -7, dirtiness +7, a happiness trend of +5, hunger +7
58|Reading a magazine|energy +5, a happiness trend of +1 || a happiness trend of -1
59|Taking a shower|dirtiness -20, dirtiness -30
60|Getting some sleep|
61|Getting some sleep|
62|Taking a nap|a happiness trend of +1, energy +15
63|Getting some sleep|
64|Getting some sleep|
65|Getting some sleep|
66|Getting some sleep|
67|Getting some sleep|
68|Getting some sleep|
69|Enjoying the patio|
70|Turning off the shower|
71|Turning off the TV|
72|Turning off the stove|
73|Turning off the stove|
74|Turning off the stove|
75|Watching TV|
76|Watching TV|
77|Watching TV|
78|Watching TV|
79|Watching TV|
80|Watching TV|
81|Watching TV|
82|Watching TV|
83|Checking weight|
84|Working on career|a piece of career work, dirtiness +1, energy -2, hunger +1
85|Working on career|a piece of career work, dirtiness +1, energy -2, hunger +1
86||
87||
88||
89||
90|Walking on the treadmill|dirtiness +8, a happiness trend of +4
91|Working out|energy -4, dirtiness +5
92|Working on career|a piece of career work, dirtiness +1, energy -2, hunger +1
93|Working on career|a piece of career work, dirtiness +1, energy -2, hunger +1
94||
95||
96||
97|Writing memoirs|
98|Admiring the bird bath.|
99|Playing in the sand|
100|Poking at the plants|energy -3, dirtiness +4, a happiness trend of +2 || energy -3, dirtiness +15, a happiness trend of +2
101|Looking for bugs|dirtiness +10 || dirtiness +20
102|Hiding|
103|Playing in the dirt|a happiness trend of +20, energy -5, dirtiness +20
104|Jumping on the bed|energy -2, energy -2, energy -2, a happiness trend of +3
105|Studying / Doing homework|energy -3, a happiness trend of +2, hunger +2
106|Chatting online|
107|Not feeling well|
108|Exercising outdoors|health +2, energy -5, a happiness trend of +3
109|Browsing Web|
110||
111|Browsing Web|
112|Dusting furniture|
113|Polishing|
114|Using the hand vacuum|
115|Playing in the rain|energy -5, dirtiness +10 to +29
116|Nature is calling!|dirtiness +40, the bathroom need -40, dirtiness -30
117|Checking out the house|
118|Celebrating|a happiness trend of +50, energy -3, the bathroom need +2, dirtiness +2
119|Organizing the closet|energy -3, a happiness trend of +10, dirtiness +2
120|Watching the rain|energy +2, a happiness trend of +130
121|Making the bed|energy -3, a happiness trend of +10, dirtiness +2
122|Cleaning the nightstand|energy -2, a happiness trend of +5, dirtiness +1
123|Doing Tai Chi|a happiness trend of +4, dirtiness +4
124|Stretching|a happiness trend of +1, dirtiness +1
126|Putting away the groceries / Peeking at the groceries|a happiness trend of +10 to +24, energy -2, a happiness trend of +4, dirtiness +2
127|Looking for laundry|energy -2
128|Making the children's beds|energy -5
129|Vacuuming the living room|a happiness trend of +2, energy -6, dirtiness +6
130|Showing baby the garden|a happiness trend of +2
131|Showing baby the toys|a happiness trend of +2
132|Changing baby's diapers|dirtiness +10
133|Cuddling|energy +5, a happiness trend of +7
134|Hiccups|
135|Watering the flowers|energy -2, dirtiness +2, a happiness trend of +2
136|Watering the flowers|energy -2, dirtiness +2, a happiness trend of +2
137|Watering the flowers|energy -2, dirtiness +2, a happiness trend of +2
138|Talking to the plants|
139|Daydreaming in the yard|
140|Celebrating marriage|
141|Celebrating a new baby|
142|Celebrating house upgrade|a happiness trend of +20
143|Taping the leaky hose|dirtiness +2, a happiness trend of +10
144|Fixing the chair|dirtiness +2, a happiness trend of +10
145|Repairing the floor|dirtiness +2, a happiness trend of +10
146|Repairing the floor|dirtiness +2, a happiness trend of +10
147|Repairing the floor|dirtiness +2, a happiness trend of +10
148|Repairing the workshop wall|
149|Repairing the workshop wall|dirtiness +2, a happiness trend of +10
150|Repairing the workshop wall|dirtiness +2, a happiness trend of +10
151|Sweeping the floor|dirtiness -6, energy -5, a happiness trend of +2
152|Taking a nap|energy +7 to +11, dirtiness +2
153|Daydreaming|energy +3, a happiness trend of +3
154|Calling children for bedtime|
155|Making children brush teeth|
156|Scared of the lightning|
157|Taking the garbage out|a happiness trend of +15
158|Arguing|a happiness trend of -10, energy -1, dirtiness +1
159|Pleading|a happiness trend of -5
160|Quick workout|energy -7, dirtiness +7, a happiness trend of +5
161|Remembering the dead|
162|Mending a button|energy -1, a happiness trend of +3
163|Ironing|energy -1, a happiness trend of +3
164|Dealing with all the socks|dirtiness +4, energy -3
165|Putting away clean shirts|dirtiness +2, energy -2
166|Swimming in the pool|dirtiness +5, energy -2, a happiness trend of +3
167|Splashing in the pool|dirtiness +8, energy -2, a happiness trend of +10
168|Having hiccups!|
169|Throat doesn't feel right|
170|Upset stomach|
171|Owww... head hurting|
172|Can't stop coughing...|
173|Itchy|
174|Sneezing|
175||
176||
177|Washing hands / Washing face|dirtiness -3
178|Putting on aftershave / Putting on makeup|a happiness trend of +1
179|Flossing|dirtiness -3
180|Brushing hair|dirtiness -1
181|Washing hair|dirtiness -15
182|Shaving / Removing makeup|dirtiness -3
183|Gargling|dirtiness -1
184|Putting in eye drops|energy +2
185|Squeezing a pimple|dirtiness +3, health -1
186|Admiring self|
187|Applying deodorant|dirtiness -3
188|Getting a drink of water|hunger -1
189|Washing feet|dirtiness -4
190|Selling a collectible online|a happiness trend of +10, energy -1
191|Hey!|a happiness trend of -3
192|Researching project online / Writing a paper for school|energy -3
193|Doing homework|energy -3, a happiness trend of +2, hunger +2
194|Taking an online test|energy -3, a happiness trend of +2, hunger +2
195|Studying on the patio|energy -3, a happiness trend of +2, hunger +2
196|Studying in the kitchen|energy -3, a happiness trend of +2, hunger +2
197|Studying|energy -3, a happiness trend of +2, hunger +2
204|Studying a recipe|
205|Thinking about cooking|
206|Cleaning the fridge|energy -2, a happiness trend of +2, dirtiness +3
207|Throwing out old food|kitchen garbage +1, a happiness trend of +2
208|Cleaning the oven|energy -2, dirtiness +3
209|Doing the dishes|energy -2, dirtiness +2
210|Cleaning kitchen counters|energy -2, dirtiness +3
211|Making coffee|energy +5
212|Checking out strange smell|kitchen garbage +1, dirtiness +4, a happiness trend of +2
213|Heating up some food|dirtiness +2, a happiness trend of +2, hunger -5
214|Having breakfast|dirtiness +3, a happiness trend of +2, hunger -8
215|Playing in the pool|hunger +2, energy -3, a happiness trend of +1
216|Eating a burger|hunger -7, energy -5, a happiness trend of +2, the bathroom need +4
217|Making a grande latte |hunger -4, the bathroom need +5, a happiness trend of +2
218|Barbecuing!|hunger -7, dirtiness +4, the bathroom need +4, a happiness trend of +4
219|Cleaning up BBQ|dirtiness +7, a happiness trend of +1
220|Playing pinball|a happiness trend of +5, dirtiness +1, energy -3
221|Running on the treadmill|dirtiness +6, a happiness trend of +2, energy -8
222|Feeding the fish|a happiness trend of +4
223|Looking at the fish|
224|Bothering the fish|
225|Admiring the Magic Fish|
226|Adjusting the painting|
227|Adjusting the painting|
228|Using the warm towel|dirtiness -2
229|Warming hands|health +1
230|Drying hair|health +1
231|Drying feet|a happiness trend of +2, health +1
232|Feeding the birds|
233|Feeling down|
234|Dancing|energy -4, a happiness trend of +2, dirtiness +2
235|Stomping ants|energy -2, a happiness trend of +2
236|Checking the outfit|
237|Reading the newspaper|a happiness trend of +1 || a happiness trend of -1
238|Mourning the dead|happiness -80
239|Lying in repose|
240|Waving goodbye|
241|Listening to the radio|a happiness trend of +4
242|Taking an insect outside|a happiness trend of +8
243|Finding annoying mosquito|a happiness trend of -5, energy -5
244|Getting attention / Telling a joke|
245|Catching grasshoppers|energy -3, dirtiness +5 to +11, a happiness trend of +5
246|Looking for mommy / Looking for daddy|
247|Feeling a bit lonely|
248|Jealous about new baby|
249|Excited about new baby|
250|Playing mommy|
251|Looking for attention|energy -2
252|Exploring|dirtiness +3 to +6, energy -2, a happiness trend of +2 to +5
253|Calling the birds|a happiness trend of +3 to +5
254|Calling children to eat|a happiness trend of +2
255|Admiring stars in the sky / Looking for a falling star|a happiness trend of +1 to +5
256|Enjoying sounds of nature|a happiness trend of +2 to +6
257|Admiring the tools|a happiness trend of -2 to -6
258|Working on hobby|a happiness trend of +2 to +8
259|Playing a board game|a happiness trend of +8
260|Shredding documents|a happiness trend of +1
261|Playing train|energy -5
262|Playing with the dishes|
263|Jumpy!|
264|Telling a story|
265|Listening to a story|
266|Tickling|
267|It tickles!|
268|Giggle party|
269|Sorting mail|a happiness trend of +2
270|Playing video games|a happiness trend of +5, energy -5, health -2
271|Hiding toys|a happiness trend of +2
272|Banging dishes!|a happiness trend of +2
273|Drawing on the wall|a happiness trend of +2, dirtiness +5
274|Measuring height|
275|There is an oven fire!|
276|The kitchen sink is leaking!|
277|The bathroom sink is leaking!|
278|The shower is clogged!|
279|The toilet is clogged!|
280|The dryer lint is burning!|
281|There is no Internet!|
282|Putting out a stove fire|dirtiness +4, a happiness trend of +1, energy -2
283|Fixing the leaky sink|dirtiness +4, a happiness trend of +1, energy -2
284|Fixing the leaky sink|dirtiness +4, a happiness trend of +1, energy -2
285|Fixing the leaky sink|dirtiness +4, a happiness trend of +1, energy -2
286|Fixing the shower|dirtiness +4, a happiness trend of +1, energy -2
287|Fixing the blocked toilet|dirtiness +4, a happiness trend of +1, energy -2
288|Putting out the laundry fire|dirtiness +4, a happiness trend of +1, energy -2
289|Fixing the router|a happiness trend of +3
290|Fixing the computers|a happiness trend of +5
291|Installing birdbath pump|
292|Installing birdbath pump|
293|Searching the shed.|
294||
295|Embracing|
296|Waiting for someone|
297|Trying to make a baby|dirtiness +8, a happiness trend of +10, energy -8, hunger +5, a try for a baby
298||
299|Dancing|
300|Relaxing|
302|Watching TV|
303|Confused|
306|Found a new item|a happiness trend of +20
307|Shaking head|
308|Shaking head|
309|Caring for baby|
310|Sitting|
311|Chatting / Praising|
312|Thinking|
313|Drinking rain|
314|Stomping ants|
315|Doing aerobics|health +1
316|Eating|hunger -5, energy -2
317|Dancing|
318||
319||
320||
321|A little bit lonely|
322|Washing baby|
323|Changing baby|
324||
325|Refusing|
326|Worried about food|
327|Chillaxing|
328|Getting out of the rain|
329|Resting in bed|
330|Needs to sit down|
331|Looking for mommy / Looking for daddy|
332|Looking for mommy|
333|Playing in puddles|
334|Secretly practicing a dance|
335|Playing in the dirt|
336|Teaching baby words|
337|Making sandcastles|
"""
ACTION_LIST = tuple((int(k), cap, tuple(o for o in outs.split(" || ") if o))
                    for k, cap, outs in (row.split("|", 2) for row in _ACTIONS.splitlines()))
ACTIONS_CHOSEN = 186          # actions whose record (0x482120, villager + id * 0xC8 + 0x2C5C) lets the chooser pick them


def _actions() -> list[Fact]:
    g, C = ACTIONS, VERIFIED_C
    groups: dict[tuple[str, tuple[str, ...]], int] = {}
    for _, cap, outs in ACTION_LIST:
        if cap:
            groups[(cap, outs)] = groups.get((cap, outs), 0) + 1
    unnamed = [outs for _, cap, outs in ACTION_LIST if not cap]
    lines = []
    for (cap, outs), n in groups.items():
        what = " Or: ".join(outs) if outs else "no need changes"
        lines.append(f"“{cap}”{f' ({n} actions)' if n > 1 else ''}: {what}.")
    return [
        Fact(g, f"The game registers {len(ACTION_LIST)} actions (the code's behaviours). Below, each with every "
                "need change its code plans, on every path through it (\u201cOr:\u201d separates paths that plan "
                "different changes). Each planned change applies once, when its step plays; a path that ends early "
                "(the place taken, the item missing) plans fewer or none. \u201cA happiness trend\u201d is the "
                "hidden trend of Needs and upkeep; hunger -N also takes N / 2 food from the house, rounded down; "
                "\u201ca piece of career work\u201d is one work roll (see Careers and promotion); \u201ca try for a "
                "baby\u201d is the conception roll (see Pregnancy and babies).", C),
        Fact(g, "Actions with the same caption and the same changes are listed once with how many there are (for "
                "example the beds' Going to bed). A caption with two names is one the code picks from (for example "
                "by the family member's sex).", C, sub=True),
        Fact(g, f"Who chooses them: {ACTIONS_CHOSEN} actions are in each family member's own choice of what to do "
                "(the weighted draw of Careers and promotion, each action with its own conditions); the others are "
                "started by the game itself, by items, drops, clicks, events, the weather or other actions.", C,
             sub=True),
        *[Fact(g, text, C, sub=True) for text in lines],
        Fact(g, f"{len(unnamed)} more actions copy no caption of their own: {sum(1 for o in unnamed if not o)} plan "
                "no need changes (10 of them only start an empty plan)"
                + ("" if all(not o for o in unnamed) else "; the rest plan: "
                   + "; ".join(o for outs in unnamed for o in outs)) + ".", C, sub=True),
        Fact(g, "Testing bevmac chunk is a developer test action left in the game; its own record keeps it out of "
                "the family members' choice.", C, sub=True),
        Fact(g, "Virtual Families 2's furniture actions (Playing pachinko, Playing foosball, Playing pool, Playing "
                "guitar, Playing piano, Hugging the bear and the rest of its placed pieces) and its Petting the pet: "
                + NOT_IN_VF1 + ".", C),
    ]


def facts() -> list[Fact]:
    """Every line of the page, in GROUPS order."""
    out = (_keys() + _time() + _needs() + _health() + _sickness() + _old_age() + _babies() + _careers() + _money()
           + _leaving() + _marriage() + _events() + _weather() + _messes() + _collectibles() + _malfunctions()
           + _store() + _store_food() + _store_meds() + _store_specials() + _store_other() + _home()
           + _career_rooms() + _drops() + _pets() + _clothing() + _trophies() + _actions() + _patcher_special()
           + _patcher_menu() + _index())
    return sorted(out, key=lambda f: GROUPS.index(f.group))      # stable: the order within a group is kept


def line(fact: Fact) -> str:
    """A fact as it reads on the page: the bullet, its label, then the words (as on the VF2 page)."""
    return f"{SUB_BULLET if fact.sub else BULLET}{fact.label}  {fact.text}"


def render(page: list[Fact] | None = None) -> str:
    """The whole page as text: the intro notes, then each group's heading and lines."""
    page = facts() if page is None else page
    parts = [INTRO, CLOCK_NOTE, PATCHER_NOTE, LABEL_NOTE, SPEED_NOTE]
    for group in GROUPS:
        lines = [line(f) for f in page if f.group == group]
        if lines:
            parts.append(group + "\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# The window (opened from the Tools tab)
# ---------------------------------------------------------------------------

LABEL_COLOURS = {VERIFIED_E: "#1b6e20", VERIFIED_C: "#245a9a", UNCONFIRMED: "#b00020"}
NOTE_RED = LABEL_COLOURS[UNCONFIRMED]
WIDTH, HEIGHT = 900, 820
MIN_WIDTH, MIN_HEIGHT = 600, 700
# 3, not 4: in 4 columns the group buttons need more than the window has at its smallest (as in the Virtual Families
# 2 patcher's window).
LINKS_PER_ROW = 3
# The group buttons sit in nine rows since the store groups and Hidden keys came in (25 groups), so they are drawn compact: a
# button's own padding is 1 pixel top and bottom instead of ttk's default, which leaves the page itself room at the
# window's smallest size.
LINK_STYLE = "Mechanics.TButton"
LINK_PADDING = (4, 1)


def open_window(parent):
    """The Game Mechanics window, laid out as the Virtual Villagers Fun Patcher's: the intro, the line that explains
    the labels in red, a button for each group, then the page in a read-only text box with its own scroll bar that
    takes the rest of the resizable window, and Close at the bottom right.  Returns the Toplevel."""
    import tkinter as tk
    from tkinter import ttk

    from vf1_tree_editor_tools import TOOL_HEADING_SPACING, tool_fonts, tool_text

    window = tk.Toplevel(parent)
    window.title(TITLE)
    width = min(WIDTH, max(MIN_WIDTH, window.winfo_screenwidth() - 80))
    height = min(HEIGHT, max(MIN_HEIGHT, window.winfo_screenheight() - 120))
    window.geometry(f"{width}x{height}")
    window.minsize(MIN_WIDTH, MIN_HEIGHT)
    window.resizable(True, True)
    outer = ttk.Frame(window, padding=12)
    outer.pack(fill="both", expand=True)
    top = ttk.Frame(outer)
    top.pack(fill="x")
    intro = ttk.Label(top, text=INTRO, wraplength=width - 60, justify="left")
    intro.pack(anchor="w")
    # What the labels mean, in red right under the intro (as the Virtual Villagers patcher's UNCONFIRMED line).
    label_note = ttk.Label(top, text=LABEL_NOTE, wraplength=width - 60, justify="left", foreground=NOTE_RED)
    label_note.pack(anchor="w", pady=(4, 8))
    top.bind("<Configure>", lambda event: (intro.configure(wraplength=max(200, event.width - 8)),
                                           label_note.configure(wraplength=max(200, event.width - 8))))
    links = ttk.Frame(outer)
    links.pack(fill="x", pady=(0, 6))
    buttons = ttk.Frame(outer)
    buttons.pack(side="bottom", fill="x", pady=(8, 0))
    body = ttk.Frame(outer)
    body.pack(fill="both", expand=True)
    fonts = tool_fonts(window)
    text = tool_text(body, wrap="word", padx=8, pady=8, borderwidth=1, relief="solid")
    bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.tag_configure("heading", font=fonts["heading"], **TOOL_HEADING_SPACING)
    text.tag_configure("note", foreground="#555555", spacing3=6)
    text.tag_configure("sub", lmargin1=28, lmargin2=48, spacing3=1)       # as the Virtual Families 2 page
    text.tag_configure("bullet", lmargin1=8, lmargin2=28, spacing3=2)
    for label, colour in LABEL_COLOURS.items():
        text.tag_configure(label, foreground=colour, font=fonts["label"])
    ttk.Style(window).configure(LINK_STYLE, padding=LINK_PADDING)

    for note in (CLOCK_NOTE, PATCHER_NOTE, SPEED_NOTE):
        text.insert("end", note + "\n", "note")
    page = facts()
    for group in GROUPS:
        text.insert("end", "\n")
        text.mark_set(f"group:{group}", "end-1c")
        text.mark_gravity(f"group:{group}", "left")
        text.insert("end", group + "\n", "heading")
        for fact in page:
            if fact.group != group:
                continue
            style = "sub" if fact.sub else "bullet"
            text.insert("end", SUB_BULLET if fact.sub else BULLET, style)
            text.insert("end", fact.label, (fact.label, style))      # the label first, as on the VF2 page
            text.insert("end", "  " + fact.text + "\n", style)
    text.configure(state="disabled")             # read-only: the page can be selected and copied, not edited

    def jump(group: str) -> None:
        text.see("end")
        text.see(f"group:{group}")

    for n, group in enumerate(GROUPS):
        ttk.Button(links, text=group, style=LINK_STYLE, command=lambda g=group: jump(g)).grid(
            row=n // LINKS_PER_ROW, column=n % LINKS_PER_ROW, sticky="we", padx=(0, 4), pady=(0, 1))
    for column in range(LINKS_PER_ROW):
        links.columnconfigure(column, weight=1)

    close = ttk.Button(buttons, text="Close", command=window.destroy)
    close.pack(side="right")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.text = text                         # for the tests
    window.mechanics_links = links
    return window


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
