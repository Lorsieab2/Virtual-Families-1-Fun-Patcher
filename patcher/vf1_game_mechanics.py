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
Nothing is inferred from save values, and code that is in the exe but not shown to run is never presented.

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
              "line the patcher's own code was run or read together with the game's in the same way.")
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
MESSES = "Messes"
COLLECTIBLES = "Collectibles"
MALFUNCTIONS = "Malfunctions"
STORE = "Store rules"
STORE_FOOD = "Store: groceries"
STORE_MEDS = "Store: medicines"
STORE_SPECIALS = "Store: specials"
STORE_OTHER = "Store: other items"
HOME = "Home Improvements"
CAREER_ROOMS = "Career Room Upgrades"
PATCHER_SPECIAL = "Patcher: Special Upgrades"
PATCHER_MENU = "Patcher: Upgrades menu"
INDEX = "Chance and timer index"
GROUPS = (TIME, NEEDS, HEALTH, SICKNESS, OLD_AGE, BABIES, CAREERS, MONEY, LEAVING, MARRIAGE, EVENTS, MESSES,
          COLLECTIBLES, MALFUNCTIONS, STORE, STORE_FOOD, STORE_MEDS, STORE_SPECIALS, STORE_OTHER, HOME, CAREER_ROOMS,
          PATCHER_SPECIAL, PATCHER_MENU, INDEX)


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
        Fact(g, "Paused, real time runs on: the store specials, food groups, symptoms and the wait between babies "
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
        Fact(g, "Whether the messes owed for the time the game was closed appear when it is loaded (the mess timer's "
                "place in the save was not traced).", U),
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
        Fact(g, "Which label sits beside which bar on the info panel.", U),
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
        Fact(g, "Whether the death animation usually removes the body before that.", U),
        Fact(g, "Causes of death the game can record: Unknown causes, Disease, Starvation, Old age. Work accident "
                "and Act of Nature are never used.", C),
        Fact(g, "Which cause the game shows for a death.", U),
    ]
    return facts


def _babies() -> list[Fact]:
    g, E, C, U = BABIES, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Only the head couple has babies: the Matriarch (the first woman at home with a career) with the "
                "Patriarch. A try for a baby rolls the chance below.", C),
        Fact(g, "How often family members try for a baby on their own.", U),
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
        Fact(g, "How often a family member goes to work.", U),
        Fact(g, "Each success pays 3% of the salary and adds progress; promotion at 3,000 progress (everyone "
                "celebrates). Successes per promotion with the career room at level 1: "
                + ", ".join(f"{n:,}" for n in successes) + "; at level 2 half as many; at level 3 "
                "8, 34, 84, 200, 250, 334, 500.", E),
        Fact(g, "Salary is paid every 3 age units (30 minutes of game time) whether or not the family member is at "
                "work, an eighth of the salary each time: a quarter of the salary per hour of real time on Normal "
                "(an eighth on Slow, half on Fast).", E),
        Fact(g, "During a catch-up, a grown-up with a career who is not sick or pregnant also gets unwatched work "
                "each age unit, each piece with a 1 in 6 (16.67%) chance of a paid success.", C),
        Fact(g, "How much unwatched work there is (it comes from a value the code does not explain).", U),
        Fact(g, "The three career rooms: room 1 is the Kitchen, room 2 the Office and room 3 the Workshop (the "
                "promotion step reads the Kitchen's level for room 1, the Office's for room 2 and the Workshop's for "
                "room 3, and each Profession Magazine works only for its own room). Upgrading them: see Career Room "
                "Upgrades.", C),
        Fact(g, "The careers, with their career room (1, 2 or 3) and salary at each level, Beginner to Master:",
             C),
    ]
    facts += [Fact(g, f"{c.name} (room {c.room}): " + ", ".join(str(s) for s in c.salaries) + ".", C, sub=True)
              for c in CAREER_LIST]
    return facts


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
        Fact(g, f"The store: the specials are drawn again when the store page opens more than {SPECIALS_REAL} "
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
        Fact(g, "The Talent Scout pop-up: its first choice sends a child away.", U),
        Fact(g, "What the game calls leaving home (college or boarding school).", U),
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
        Fact(g, "The Little Visitor Popup Event: its first choice adds a child to the family.", U),
    ]


# (title, kind, effect, label): docs/game-mechanics/spec.md section 11 (events_registry.tsv, events_emulated.txt)
_EVENTS = (
    ("1 A Secret Admirer", "Email Event", "nothing seen", VERIFIED_E),
    ("2 / 3 Electric Bill Correction", "Email Event", "-$5 to $24 / +$5 to $24", VERIFIED_E),
    ("4 Spam \"Funny\"", "", "never comes", VERIFIED_C),
    ("5 / 6 Professional Association Fee / Rebate", "Email Event", "-$5 to $7 / +$5 to $14", VERIFIED_E),
    ("7 Professional Network, 8 Professional Association Award", "Email Event", "career progress for one family member",
     UNCONFIRMED),
    ("9 Infringement Complaint", "Email Event", "nothing seen", UNCONFIRMED),
    ("10 / 11 Tax Audit", "Email Event", "-$100 / +$100", VERIFIED_E),
    ("12 to 15 Spam (Bigger Brain, Nigerian Lottery, Car Insurance, What's What)", "Email Event", "nothing", VERIFIED_E),
    ("16 to 18 Old Friend", "Email Event", "nothing", VERIFIED_E),
    ("19 Oh! A collectible!", "Email Event", "a rare collectible", VERIFIED_C),
    ("20 My Weather Machine", "Email Event", "what it changes", UNCONFIRMED),
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
    ("37 Earthquake, 38 Aesthetic Society", "Popup Event", "what they do", UNCONFIRMED),
    ("39 Birdwatcher Society", "Popup Event", "+$25, $50, $75 or $100", VERIFIED_E),
    ("40 Allergy Season", "Popup Event", "family members get a symptom (how many is not confirmed)", VERIFIED_E),
    ("41 Adoption Day", "Popup Event", "everyone celebrates", VERIFIED_E),
    ("42 TV Night, 43 BBQ Party", "Popup Event", "everyone joins in (needs the item)", VERIFIED_E),
    ("44 The Broken Window", "Popup Event", "+$1 to $30", VERIFIED_E),
    ("45 Photo Contest, 46 Community Association", "Popup Event", "+$25 to $125 / -$20 to $100", VERIFIED_E),
    ("47 Blowing Trash, 48 Free Lawn Service", "Popup Event", "5 to 12 wrappers in the house / 5 to 12 weeds in the yard",
     VERIFIED_E),
    ("49 / 50 The Little Visitor", "Popup Event", "first choice: a child joins", UNCONFIRMED),
    ("51 Small Package, 52 Medium Brown Box, 53 Sealed Green Bag", "Popup Event", "first choice: an item", UNCONFIRMED),
    ("54 A Tiny White Box", "Popup Event", "first choice: a third of the food is gone", VERIFIED_E),
    ("55 Scratch-Off Lottery Ticket", "Popup Event", "what it does", UNCONFIRMED),
    ("56 The Wrong Address", "Popup Event", "first choice: -$100 and the Sheets and Pillows home improvement; it "
     "comes only while the family has no Sheets and Pillows and has $99 or more", VERIFIED_C),
    ("57 The Delivery Truck", "Popup Event", "first choice: the Collection of Paintings home improvement; it comes "
     "only while the family has none (whether it costs money is not confirmed)", VERIFIED_C),
    ("58 The Talent Scout", "Popup Event", "first choice: a child leaves home", UNCONFIRMED),
    ("59 The Beauty Contest", "Popup Event", "first choice: -$10 (any prize is not confirmed)", VERIFIED_E),
    ("60 Landscaping, 61 Housekeeping", "Popup Event",
     "never shown: each has choices but no family member to act on, so the game skips them (0x41AAE1..0x41AAF1)",
     VERIFIED_C),
    ("62 Total House Care", "Popup Event", "first choice: -$50 (the cleaning itself is not confirmed)", VERIFIED_E),
    ("63 The Mysterious Collector", "Popup Event", "what it does", UNCONFIRMED),
    ("64 Water Pressure Surge", "Popup Event", "second choice: five leaks", VERIFIED_C),
    ("65 Professional Career Training", "Popup Event", "first choice: -$250 (the promotion is not confirmed)", VERIFIED_E),
    ("66 The Trainer", "Popup Event", "first choice: -$5 and all the food is gone", VERIFIED_E),
    ("67 The Cooking Class", "Popup Event", "first choice: a kitchen mess", VERIFIED_C),
    ("68 The Power Failure", "Popup Event", "first choice: food set to 50 to 99; second: a family member gets a symptom",
     VERIFIED_E),
    ("69 Career Change Counselor", "Popup Event", "first choice: a new career", UNCONFIRMED),
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
        Fact(g, "Whether a blue sock vanishes as soon as it appears.", U),
    ]


def _collectibles() -> list[Fact]:
    g, E, C, U = COLLECTIBLES, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "A collectible may appear every frame with the code's 3 in 6,600 roll, exactly 15 in 32,768 "
                "(0.0458%). Frames run on real time, so this is the same at any speed; none while paused.", C),
        Fact(g, upgrade("Lucky Rock", "$77,777", "a 3 in 3,300 roll, exactly 30 in 32,768 (0.0916%) a frame "
                                                 "(real time), so twice as often."), E, sub=True),
        Fact(g, "How that turns into real time (about one every 73 seconds of real time if the game draws 30 "
                "frames a second).", U),
        Fact(g, "Rarity: rare 4.00%, uncommon 13.01%, common 82.98%. Nothing appears if that item is already "
                "out or being carried, or (photo pieces) already owned.", C),
        Fact(g, upgrade("Lucky Rock", "$77,777", "rare 8.01%, uncommon 26.03%, common 65.97%."), E, sub=True),
        Fact(g, "Selling a duplicate: $5 common, $15 uncommon, $50 rare.", C),
        Fact(g, "A collectible stays on the ground for 2 minutes of real time.", U),
    ]


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
        Fact(g, "Which malfunction is which (leaks, clogged shower, dryer lint fire, power).", U),
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
                "(the eight medicines, Baby Boost and the Doctor Consultation); six more places hold the specials, "
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
        Fact(g, f"The specials (six places): every {SPECIALS_REAL}, the six are drawn again, at random, from the "
                "items that may appear (each special entry below says when it may), at the first opening of the "
                "store page after that time. An item cannot fill two places at once.", C),
        Fact(g, f"On Sale: one grocery bag (organics included) at half price, drawn again at the first opening of "
                f"the store page more than {game_span(SALE_GAME_SECONDS)} after the last draw. Buying it on sale "
                "adds the price paid to the \"Coupon clipper\" trophy.", C),
        Fact(g, with_patcher("CheatUpgrades", f"{CHEATS_PAGE} multiplies every store price, the career rooms "
                             "included, by 2, 5 or 100 (rounded down after the Food Club and Health Plan discounts; at "
                             "most $2,147,483,647). Choosing the same multiplier again, or Reset, goes back to the "
                             "listed prices. Returns give back the multiplied price at the time of the return."),
             C, sub=True),
        Fact(g, with_patcher("FleaMarket", "the Upgrades menu's Flea Market sells every tray item except groceries "
                             "and outfits (items 12 to 17 and 20 to 63: drinks, candies, fruit, medicines, Baby Boost, "
                             "the Doctor Consultation, care items, repair items, Anti-spam Software, magazines, films, "
                             "bottles, kits, the book and the pets) at their listed price, at any time, without the "
                             "store's stock or specials; its Get for free button gives the item at no cost. Each "
                             "works as described below."), C),
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
    any_time = "It may appear among the specials at any time."
    return [
        Fact(g, "Each special below is dropped on one family member unless it says otherwise, and is used up. "
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
                "the specials never offer it again.", C, sub=True),
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
        Fact(g, item(55, "+1 to +3 happiness, and at once the sky turns to the rain on its label. Insect "
                         "collectibles appear only while the sky is in one of two of its four states, the rain this "
                         "bottle brings being one. " + any_time), C),
        Fact(g, item(56, "+1 to +3 happiness, and at once the sky turns to the sunshine on its label. "
                         + any_time), C),
        Fact(g, f"How long it lasts, on the game clock (game time): the rain 392 to 751 game seconds "
                f"({game_range(392, 751)}), the sunshine 932 to 2,431 ({game_range(932, 2_431)}). The "
                "bottle holds its sky for 30 game seconds, then sets it again with the sky's own length (rain 360 to "
                "719, sunshine 900 to 2,399); after the rain comes sunshine, after the sunshine one of the other three "
                "skies, one of which never comes at night (checked, every roll at its lowest and highest). Paused, the "
                "game clock stops, so the sky does not change.", E, sub=True),
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
                "last draw. Buying one keeps the picture drawn then, and every outfit of that kind in the tray gives "
                "the picture of the last one bought (checked: a Male Outfit bought at picture 7 gives 7; after a "
                "redraw to 12 it still gives 7; once a second is bought, both give 12).", E, sub=True),
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
        Fact(g, item(42, "never offered: the specials draw skips it, so in the stock game the broken chair it "
                         "repairs can never be mended. Dropped on the broken chair, its repair could start."), C),
        Fact(g, with_patcher("FleaMarket", "the Flea Market sells the Wood Furniture Repair Kit ($50), so the "
                             "chair can be repaired."), C, sub=True),
        Fact(g, "Ball ($10 in the item table, never used up): dropping it on a family member does nothing (the drop "
                "handler has no use for it).", C),
        Fact(g, "The store never offers the Ball: its specials table lists it in the first special place, but the "
                "first opening of the store page fills all six places, with a draw, or in a new family's first 2 "
                "seconds of real time with the kept specials, empty then (checked: the Ball is gone after either); the draw "
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
    ("Patio Furniture: \"Enjoying the patio\" and \"Studying on the patio\" change no need or stat.", VERIFIED_E,
     True),
    ("Both only while the sky is sunny. Enjoying: any age, health 12 or more, hunger 75 or less, energy 65 or less. "
     "Studying: ages 14 to 18, happiness 25 or more, hunger 60 or less, energy 35 or more.", VERIFIED_C, True),
    ("Swimming Pool: \"Swimming in the pool\": +5 dirtiness, -2 energy and a happiness trend of +3. \"Splashing in "
     "the pool\": +8 dirtiness, -2 energy and a happiness trend of +10. \"Playing in the pool\": +2 hunger, -3 "
     "energy and a happiness trend of +1.", VERIFIED_E, True),
    ("All three not pregnant, with health 30 or more, happiness 40 or more, hunger 75 or less and energy 25 or "
     "more. Swimming and Playing: any age, only while the sky is sunny, hunger 5 or more. Splashing: aged 14 or "
     "under, in any sky, hunger 20 or more.", VERIFIED_C, True),
    ("Hammock: \"Relaxing in the hammock\": a happiness trend of -1, and nothing else.", VERIFIED_E, True),
    ("For any age, only while the sky is sunny, with happiness 25 or more, hunger 75 or less and energy 65 or "
     "less.", VERIFIED_C, True),
    ("Outdoor Barbecue Grill: \"Barbecuing!\": -7 hunger and 3 food used, +4 dirtiness, +4 bathroom need and a "
     "happiness trend of +4. \"Cleaning up BBQ\": +7 dirtiness and a happiness trend of +1.", VERIFIED_E, True),
    ("Both for family members aged 14 or older who are not pregnant, only while the sky is sunny, with health 15 or "
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
                      "Software Ownership (see Store: specials)."), C),
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
        Fact(g, with_patcher("FleaMarket", "Flea Market: see Store rules."), C),
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
    ("Store specials", SPECIALS_REAL + ", drawn when the store page opens", VERIFIED_C),
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
        Fact(g, f"4,492 of them are in the family members' {REGISTERED_ACTIONS} actions (how long an action lasts, which variant, "
                "where they walk). What those actions give was not decoded.", U),
        Fact(g, "The rest are setup, looks, names, the screen and input; the two largest groups (58 and 57 rolls) "
                "were not decoded.", U),
    ]
    return facts


def facts() -> list[Fact]:
    """Every line of the page, in GROUPS order."""
    out = (_time() + _needs() + _health() + _sickness() + _old_age() + _babies() + _careers() + _money()
           + _leaving() + _marriage() + _events() + _messes() + _collectibles() + _malfunctions() + _store()
           + _store_food() + _store_meds() + _store_specials() + _store_other() + _home() + _career_rooms()
           + _patcher_special() + _patcher_menu() + _index())
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
# The group buttons sit in eight rows since the store groups came in (24 groups), so they are drawn compact: a
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
