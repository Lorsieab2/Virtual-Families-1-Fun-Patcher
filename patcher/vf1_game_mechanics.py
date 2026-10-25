"""Game Mechanics: how Virtual Families works underneath, from the stock game's own code (the Tools tab's window).

The model is the Virtual Villagers Fun Patcher's Game Mechanics window: the rules are grouped (GROUPS), every
line is a bullet with its evidence label right beside it, and every time is a real time.  It is for the
curious and it only reads: it opens no save, game file or install, and writes nothing.

EVIDENCE.  Every line carries one label, always shown (docs/game-mechanics/spec.md, "Evidence labels"):
  VERIFIED-E   the game's own routine was run as linked (in an emulator) with the inputs the game supplies, and
               its odds counted over every value of the game's random number;
  VERIFIED-C   the rule is the game's own instruction sequence, on a call path traced from the running game;
  UNCONFIRMED  anything else: not on a traced path, reached only from player input that was not traced, a
               meaning the code does not show, or the patcher's own features read from its source.
Nothing is inferred from save values, and code that is in the exe but not shown to run is never presented.

SPEEDS.  VF1's speed value is a divisor (10 = Normal, the only speed the stock game sets).  One age unit takes
60 x speed real seconds and a game second takes speed / 10 real seconds.  The patcher's Time Controls patch adds
Slow (20) and Fast (5), and 5x (2) and 10x (1); it always saves a family at Normal (or Paused) and loads any other
saved speed as Normal, so the time a closed game catches up on is always counted at Normal.  Times are written
for Normal with Slow and Fast beside them.  Paused (the speed plus 999) stops the game clock (spec commit
db2d45a: CGameTime::SetSpeed stores speed 0 and Seconds() returns the banked value).

The owner's four decisions were each re-checked in the stock exe before going in (Game Mechanics branch,
2026-10-25); only what held is shown:
  * Interest has no cap on missed days: shown (UpdateInterest 0x422830 emulated for 1..100 days, called every
    3 age units from the happiness update 0x48FFB2 <- upkeep 0x48BD57 <- 0x424F93 <- UpdateScene 0x444E9A).
  * Malfunctions roll while paused: shown (the 2-second step 0x444E28..0x444FEC run at speed 1009 rolls
    rand(800) and calls SetProp 0x4938C0; GameUpdate 0x422D90 and Run 0x402CC0 call the scene with no pause test).
  * The hidden fifth food-group slot: NOT shown.  FoodGroupsActive 0x48FE30 counts the extra group for a
    family member without a career only while the low byte of the Grains slot's expiry is non-zero: one with
    only Dairy counts 1, not 2, and one whose Grains ran out still counts 1 with no group at all.  "Any food
    group counts one extra" is therefore not the game's rule; the tables below are for family members with
    a career, who count each active group once.
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

INTRO = ("For the curious: how Virtual Families works underneath, worked out from the game's own code. All times "
         "are real times. It only reads: no save or game file is opened or changed, so the game may be running.")
LABEL_NOTE = ("Every line says what stands behind it. VERIFIED-E: the game's own code was run with the values the "
              "game gives it, and the chances counted exactly. VERIFIED-C: read in the game's own code, on a path the "
              "running game is shown to take. UNCONFIRMED: not yet shown either way.")
SPEED_NOTE = ("Times are for Normal speed, the only speed the stock game has; Slow and Fast are the Time Controls "
              "patch's speeds (Slow is half speed, Fast double). Chances are the game's exact odds: its random "
              "numbers make \"less than 30 in 100\" 30.03%, not 30%.")

BULLET, SUB_BULLET = "• ", "    – "

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
EVENTS = "E-mail and pop-up events"
MESSES = "Messes"
COLLECTIBLES = "Collectibles"
MALFUNCTIONS = "Malfunctions"
INDEX = "Chance and timer index"
GROUPS = (TIME, NEEDS, HEALTH, SICKNESS, OLD_AGE, BABIES, CAREERS, MONEY, LEAVING, MARRIAGE, EVENTS, MESSES,
          COLLECTIBLES, MALFUNCTIONS, INDEX)


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
    """'X on Normal, Y on Slow, Z on Fast' for a function of the speed giving real seconds."""
    return (f"{duration(real_at(NORMAL))} on Normal, {duration(real_at(SLOW))} on Slow, "
            f"{duration(real_at(FAST))} on Fast")


def units_text(units: float) -> str:
    return at_speeds(lambda speed: unit_seconds(units, speed))


def game_text(game: float) -> str:
    return at_speeds(lambda speed: game_seconds(game, speed))


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
        Fact(g, "Game speed: the stock game only ever runs at Normal. The Time Controls patch adds Slow (half "
                "speed), Fast (double speed), 5x and 10x.", C),
        Fact(g, "Time Controls speeds never reach a save: the game saves a family at Normal (or Paused) and loads "
                "any other saved speed as Normal. So the time while the game is closed is always counted at "
                "Normal.", C),
        Fact(g, f"Ageing: one age unit every {units_text(1)}. Twenty age units are one year: "
                f"{units_text(YEAR_UNITS)}.", E),
        Fact(g, "Ageing runs on real time: each family member counts the real seconds since their last update, "
                "including the time the game is closed (within the time-away limits below).", C),
        Fact(g, "Paused: the game clock stops, so nothing that runs on game time moves (interest, events, the "
                "dating e-mail, the store); messes and collectibles stop too.", C),
        Fact(g, "Paused: nobody ages, and the paused time is never added on later (checked with 3 days paused: "
                "no ageing at all).", E),
        Fact(g, "Day and night follow your PC's clock (12 hours later with Reverse Day/Night), at every speed.", C),
        Fact(g, "Time away, while the game is closed (counted at Normal, see above):", E),
        Fact(g, "up to 8 hours 36 minutes 40 seconds (31,000 seconds) away: counted in full.", E, sub=True),
        Fact(g, "longer than that, up to exactly 24 hours: counted as 8 hours 36 minutes 40 seconds "
                f"({31_000 // (AGE_UNIT_SECONDS * NORMAL)} age units, about 2.6 years).", E, sub=True),
        Fact(g, "more than 24 hours: counted as 24 hours (144 age units, 7.2 years).", E, sub=True),
        Fact(g, "at Slow the same check counts in full up to 6 hours 36 minutes 40 seconds, then 8 hours 36 "
                "minutes 40 seconds up to 24 hours; at Fast in full up to 10 hours 36 minutes 40 seconds, then 8 "
                "hours 36 minutes 40 seconds; more than 24 hours is 24 hours at every speed.", E, sub=True),
        Fact(g, "a gap is caught up all at once: every counted age unit runs its hunger, health, sickness, "
                "birthday and birth checks before the house is drawn again.", E, sub=True),
        Fact(g, "\"Where have you been?\" is shown after more than 23 hours away.", C, sub=True),
        Fact(g, "Whether game time (interest, events, the store) also runs while the game is closed.", U),
    ]


def _needs() -> list[Fact]:
    g, E, C, U = NEEDS, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "Every 2 real seconds the game updates the family, at every speed.", C),
        Fact(g, "Each family member at home and alive then runs the checks below once for every age unit they "
                "have aged since.", E),
        Fact(g, f"Hunger: +5 every 4 age units ({units_text(4)}); above 80 it rises by 2 instead.", E),
        Fact(g, "Hunger never goes above 100.", C),
        Fact(g, "Eating, each age unit: a hungry family member (hunger over 50) eats 3 food and loses 3 hunger - "
                "always with more than 50 food in the house, 50.05% of the time with 50 or less.", E),
        Fact(g, "Not eating (no food, or the missed 50.05%) when there is some food: 30.03% chance of losing 1 "
                "health (recorded as Starvation).", E),
        Fact(g, "Waste: with 1,000 food or more, a hungry family member has a 76.05% chance each age unit of "
                "using 3 more food.", E),
        Fact(g, "Bathroom need (\"poo\" in the save): at 90 or more it drops to 25 to 49.", E),
        Fact(g, "Food groups on this page are as counted for a family member with a career: each active group "
                "once.", E),
        Fact(g, "Health, happiness and sickness are checked every 3 age units "
                f"({units_text(3)}).", E),
        Fact(g, "Energy (every other age unit, only the last 12 of a catch-up; it reads your PC's clock): -4 between 8 PM and 5 AM (from 10 "
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
                "group to every family member at home for 24 real hours, at any speed. Groceries add 150 food, "
                "organics 250 food and a little happiness.", E),
        Fact(g, "Food in the house starts at 50 to 99, never goes below 0 and has no top limit. Food only changes "
                "through eating, bags, events and the patcher's Food Club - there is no daily use.", C),
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
                f"health, 0 after 90 age units, {units_text(90)}, even with every per-unit loss missed).", E),
    ]


def _sickness() -> list[Fact]:
    g, E, U = SICKNESS, VERIFIED_E, UNCONFIRMED
    return [
        Fact(g, f"A healthy family member is checked every 3 age units ({units_text(3)}). Chance of falling ill "
                "for a family member with a career (any sickness / a symptom / a mild infection / a serious one):",
             E),
        Fact(g, "0, 1, 2 or 4 food groups: 1.007% / 0.906% / 0.071% / 0.030%.", E, sub=True),
        Fact(g, "exactly 3 food groups: 0.806% / 0.725% / 0.056% / 0.024%.", E, sub=True),
        Fact(g, "anyone at home already has a symptom: 2.518% / 2.266% / 0.176% / 0.076%, and the symptom "
                "caught is that person's first one.", E, sub=True),
        Fact(g, "A symptom lasts 6 to 17 real hours, at any speed; with only symptoms, the first one goes when its "
                "time is up.", E),
        Fact(g, "Mild infection: each check, 50.05% chance of a new symptom when there is none; it ends with a "
                "3.00% chance.", E),
        Fact(g, "Serious infection: each check, 50.05% chance of a new symptom while there are fewer than 2; it "
                "ends with a 1.21% chance.", E),
        Fact(g, "Being sick: 61% health loss per age unit, no recovery, -3 energy, a happiness trend of -150, a "
                "health-check roll, and slower unwatched work.", E),
        Fact(g, "The seven symptoms' names and which medicine cures which.", U),
        Fact(g, "What the medicines, the Doctor Consultation and Baby Boost do.", U),
    ]


def _old_age() -> list[Fact]:
    g, E, C, U = OLD_AGE, VERIFIED_E, VERIFIED_C, UNCONFIRMED
    facts = [
        Fact(g, "Old age is rolled on birthdays only. The safe age is 55 years, plus 1 year for each food group "
                "counted, 1 for the Air Purifier, 1 for the Bathroom Upgrade and 3 if health is over 90. Past it, "
                "the chance of dying on a birthday is 10% for each year over (100% at 10 years over).", E),
        Fact(g, "Chance of dying on a birthday, for a family member with a career, health 90 or less, no "
                "upgrades (10% / 50% / 100% at):", E),
    ]
    for groups in range(5):
        start = 56 + groups
        facts.append(Fact(g, f"{groups} food group{'s' if groups != 1 else ''}: {start} / {start + 4} / "
                             f"{start + 9}.", E, sub=True))
    facts += [
        Fact(g, "each upgrade moves those ages 1 year later, and health over 90 moves them 3 years later.", E,
             sub=True),
        Fact(g, "No family member can live past 75.", E),
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
        Fact(g, "Fertility is 15 to 89 when a family member is made, and kept 1 to 100.", E),
        Fact(g, "Twins and triplets: single 93.0%, twins 5.25%, triplets 1.75%; each parent's fertility over 85 "
                "adds its excess to both chances. Needs free child places (6 children per generation).", C),
        Fact(g, f"Pregnancy lasts 21 age units: {units_text(21)}.", E),
        Fact(g, "A baby joins the family at age 2 (40 age units). While the family is 6 or fewer, the baby's sex "
                "is chosen to balance the house.", C),
        Fact(g, "Wait before the next baby (real time, any speed): after a birth, 10 minutes to 4 hours 10 "
                "minutes, longer the less both parents want children; after a try that fails, 20 minutes and a "
                "dip in the mother's happiness; marrying clears it. Trying too soon gives the \"too soon\" "
                "response and moves the wait to 55 minutes if it was under an hour.", C),
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
        Fact(g, "Salary is paid every 3 age units whether or not the family member is at work: a quarter of the "
                "salary per real hour on Normal (an eighth on Slow, half on Fast).", E),
        Fact(g, "During a catch-up, a grown-up with a career who is not sick or pregnant also gets unwatched work "
                "each age unit, each piece with a 1 in 6 (16.67%) chance of a paid success.", C),
        Fact(g, "How much unwatched work there is (it comes from a value the code does not explain).", U),
        Fact(g, "Career room upgrades cost $0 / $5,000 / $15,000, and how they are bought.", U),
        Fact(g, "Which of the three career rooms is which.", U),
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
        Fact(g, f"Interest: 10% of the money a game day, every {game_text(86_400)}.", C),
        Fact(g, "Interest has no limit on missed days: every whole game day since it was last due is paid at "
                "once, 10% of the money for each day (checked: 1, 2, 3, 7, 30 and 100 days on $1,000 pay $100, "
                "$200, $300, $700, $3,000 and $10,000).", E),
        Fact(g, "Interest is paid when the family's happiness updates (every 3 age units), and when the bank, the "
                "store or an event checks it.", C),
        Fact(g, "Paused, no interest builds up: it runs on game time.", C),
        Fact(g, f"The store: the specials change every {game_text(14_400)}; one grocery bag is half price, "
                f"changing every {game_text(43_200)}.", C),
        Fact(g, "The patcher's Brokerage Account (11% interest), Food Club (+500 food a game day missed, half-price "
                "groceries), Health Plan (medicines at a quarter price), Maid and Gardener (hourly visits that "
                "clear the mess and the weeds).", U),
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
        Fact(g, f"The first dating e-mail comes {game_text(180)} after the head (or heir) joins. After the dating "
                "page is opened, the next is 5 game minutes later for each proposal so far plus 10 for each year "
                "the head is over 26. It comes only when exactly one family member aged 14 or more is at home.",
             C),
        Fact(g, "Each candidate is the opposite sex, 3 years younger to 2 years older than the head, with a "
                "dowry of $35 to $209, doubled 15.01% of the time. Asking for another candidate loses this "
                "one.", C),
        Fact(g, "Marrying pays the dowry, puts the spouse in the family tree and clears the wait for a baby.", C),
        Fact(g, "The next generation: when a parent with children dies and a child is still alive, the family "
                "tree offers it. Choosing an heir hides every other family member. Nobody remarries while "
                "there are children in the record.", C),
        Fact(g, "At most 6 children per generation, 30 family members in a save and 30 generations.", C),
        Fact(g, "Adoption Day (a pop-up): everyone celebrates; nobody joins or leaves.", E),
        Fact(g, "The Little Visitor pop-up: its first choice adds a child to the family.", U),
    ]


# (title, kind, effect, label): docs/game-mechanics/spec.md section 11 (events_registry.tsv, events_emulated.txt)
_EVENTS = (
    ("1 A Secret Admirer", "e-mail", "nothing seen", VERIFIED_E),
    ("2 / 3 Electric Bill Correction", "e-mail", "-$5 to $24 / +$5 to $24", VERIFIED_E),
    ("4 Spam \"Funny\"", "", "never comes", VERIFIED_C),
    ("5 / 6 Professional Association Fee / Rebate", "e-mail", "-$5 to $7 / +$5 to $14", VERIFIED_E),
    ("7 Professional Network, 8 Professional Association Award", "e-mail", "career progress for one family member",
     UNCONFIRMED),
    ("9 Infringement Complaint", "e-mail", "nothing seen", UNCONFIRMED),
    ("10 / 11 Tax Audit", "e-mail", "-$100 / +$100", VERIFIED_E),
    ("12 to 15 Spam (Bigger Brain, Nigerian Lottery, Car Insurance, What's What)", "e-mail", "nothing", VERIFIED_E),
    ("16 to 18 Old Friend", "e-mail", "nothing", VERIFIED_E),
    ("19 Oh! A collectible!", "e-mail", "a rare collectible", VERIFIED_C),
    ("20 My Weather Machine", "e-mail", "what it changes", UNCONFIRMED),
    ("21 An extra hammock", "e-mail", "everyone goes to the yard", VERIFIED_E),
    ("22 Birthday present, 23 Preferred Customer Rebate, 24 Craft Fair", "e-mail",
     "+$10 to $50 / +$5 to $79 / +$35 to $45", VERIFIED_E),
    ("25 / 26 The Rebate", "e-mail", "nothing / +$50", VERIFIED_E),
    ("27 Helpful Child, 28 Bad Cookies", "e-mail", "+$5 to $54 / -$5 to $100", VERIFIED_E),
    ("29 / 30 Office Collection, 33 Overdue Book, 35 Bake Sale", "e-mail",
     "-$4 to $40 / -$5 to $50 / -$5 to $50 / -$6 to $60", VERIFIED_E),
    ("31 Best Landscape Award, 32 Kite Contest, 34 Hot Dog Contest", "e-mail", "+$5 to $50 / +$8 to $80 / +$5 to $50",
     VERIFIED_E),
    ("36 Neighborhood Children's Association", "pop-up", "-$20 (with 2 children)", VERIFIED_E),
    ("37 Earthquake, 38 Aesthetic Society", "pop-up", "what they do", UNCONFIRMED),
    ("39 Birdwatcher Society", "pop-up", "+$25, $50, $75 or $100", VERIFIED_E),
    ("40 Allergy Season", "pop-up", "family members get a symptom (how many is not confirmed)", VERIFIED_E),
    ("41 Adoption Day", "pop-up", "everyone celebrates", VERIFIED_E),
    ("42 TV Night, 43 BBQ Party", "pop-up", "everyone joins in (needs the item)", VERIFIED_E),
    ("44 The Broken Window", "pop-up", "+$1 to $30", VERIFIED_E),
    ("45 Photo Contest, 46 Community Association", "pop-up", "+$25 to $125 / -$20 to $100", VERIFIED_E),
    ("47 Blowing Trash, 48 Free Lawn Service", "pop-up", "5 to 12 wrappers in the house / 5 to 12 weeds in the yard",
     VERIFIED_E),
    ("49 / 50 The Little Visitor", "pop-up", "first choice: a child joins", UNCONFIRMED),
    ("51 Small Package, 52 Medium Brown Box, 53 Sealed Green Bag", "pop-up", "first choice: an item", UNCONFIRMED),
    ("54 A Tiny White Box", "pop-up", "first choice: a third of the food is gone", VERIFIED_E),
    ("55 Scratch-Off Lottery Ticket", "pop-up", "what it does", UNCONFIRMED),
    ("56 The Wrong Address", "pop-up", "first choice: -$100 (what you get is not confirmed)", VERIFIED_E),
    ("57 The Delivery Truck", "pop-up", "what it does", UNCONFIRMED),
    ("58 The Talent Scout", "pop-up", "first choice: a child leaves home", UNCONFIRMED),
    ("59 The Beauty Contest", "pop-up", "first choice: -$10 (any prize is not confirmed)", VERIFIED_E),
    ("60 Landscaping, 61 Housekeeping, 62 Total House Care", "pop-up",
     "first choice: -$20 / -$20 / -$50 (the cleaning itself is not confirmed)", VERIFIED_E),
    ("63 The Mysterious Collector", "pop-up", "what it does", UNCONFIRMED),
    ("64 Water Pressure Surge", "pop-up", "second choice: five leaks", VERIFIED_C),
    ("65 Professional Career Training", "pop-up", "first choice: -$250 (the promotion is not confirmed)", VERIFIED_E),
    ("66 The Trainer", "pop-up", "first choice: -$5 and all the food is gone", VERIFIED_E),
    ("67 The Cooking Class", "pop-up", "first choice: a kitchen mess", VERIFIED_C),
    ("68 The Power Failure", "pop-up", "first choice: food set to 50 to 99; second: a family member gets a symptom",
     VERIFIED_E),
    ("69 Career Change Counselor", "pop-up", "first choice: a new career", UNCONFIRMED),
    ("70 The Rare Bird", "pop-up", "what it does", UNCONFIRMED),
    ("71 School Fund-raiser", "pop-up", "first choice: -$25 and +100 food", VERIFIED_E),
)


def _events() -> list[Fact]:
    g, C, U = EVENTS, VERIFIED_C, UNCONFIRMED
    facts = [
        Fact(g, f"An event is checked every {game_text(3_600)}. The first check comes {game_text(900)} after "
                "a new family starts. Paused, none come.", C),
        Fact(g, "At each check a random family member is picked; if they are alive, caught up and no e-mail is "
                "waiting, it is an e-mail 66.02% of the time and a pop-up 33.98%. Otherwise the check waits and "
                "tries again straight away.", C),
        Fact(g, "Each event that can happen is equally likely, and events repeat.", C),
        Fact(g, "The 71 events (what the first and second choices do, money as a range):", C),
    ]
    facts += [Fact(g, f"{title}{f' ({kind})' if kind else ''}: {effect}.", label, sub=True)
              for title, kind, effect, label in _EVENTS]
    facts.append(Fact(g, "The patcher's Roll the Dice: $500 for a pop-up event (refunded if none can come).", U))
    return facts


def _messes() -> list[Fact]:
    g, C, U = MESSES, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, f"With fewer than 4 in the family a mess appears every {game_text(18_000)}; with 4 or more, "
                f"every {game_text(9_000)}. None while paused. Up to 30 at once, house and yard "
                "together.", C),
        Fact(g, "What it is: a cobweb 20% (when none is out), a weed in the yard 10% (30% while a cobweb is out), "
                "a sock 25%, a candy wrapper 25%, a dirt smudge 20%.", C),
        Fact(g, "Socks, weeds, wrappers and smudges together lower happiness at 10 and at 20; a clean house (0) "
                "or 1 to 4 raises it.", C),
        Fact(g, "The kitchen garbage is full at 20.", C),
        Fact(g, "Whether a blue sock vanishes as soon as it appears.", U),
    ]


def _collectibles() -> list[Fact]:
    g, C, U = COLLECTIBLES, VERIFIED_C, UNCONFIRMED
    return [
        Fact(g, "A collectible may appear every frame with a 3 in 6,600 chance, at any speed; none while "
                "paused.", C),
        Fact(g, "How that turns into real time (about one every 73 seconds if the game draws 30 frames a "
                "second).", U),
        Fact(g, "Rarity: rare 4.00%, uncommon 13.01%, common 82.99%. Nothing appears if that item is already "
                "out or being carried, or (photo pieces) already owned.", C),
        Fact(g, "Selling a duplicate: $5 common, $15 uncommon, $50 rare.", C),
        Fact(g, "A collectible stays on the ground for 2 real minutes.", U),
        Fact(g, "The patcher's Lucky Rock: rare 8%, uncommon 26%, common 66%.", U),
    ]


def _malfunctions() -> list[Fact]:
    g, E, U = MALFUNCTIONS, VERIFIED_E, UNCONFIRMED
    return [
        Fact(g, "Every 2 real seconds, at any speed and also while the game is paused, a house malfunction has a "
                "1 in 800 chance (exactly 41 in 32,768): on average one every 26.6 real minutes.", E),
        Fact(g, "Only when no malfunction is already happening; then one of 8 is picked at random, and none "
                "happens if that one's permanent fix has been bought.", E),
        Fact(g, "Which malfunction is which (leaks, clogged shower, dryer lint fire, power).", U),
    ]


_TIMERS = (
    ("Family update", "every 2 real seconds, at any speed, also while paused", VERIFIED_C),
    ("Age unit", units_text(1), VERIFIED_E),
    ("Pregnancy", units_text(21), VERIFIED_E),
    ("Body removed", units_text(240), VERIFIED_E),
    ("Wait between babies", "10 minutes to 4 hours 10 minutes real time; 20 minutes after a failed try",
     VERIFIED_C),
    ("Symptom", "6 to 17 real hours", VERIFIED_E),
    ("Food group", "24 real hours", VERIFIED_C),
    ("Interest", game_text(86_400) + ", every missed day paid", VERIFIED_E),
    ("Event check", game_text(3_600) + "; the first " + game_text(900), VERIFIED_C),
    ("Dating e-mail", game_text(180) + " for the first", VERIFIED_C),
    ("Mess", game_text(18_000) + "; half that with 4 or more", VERIFIED_C),
    ("Store specials", game_text(14_400), VERIFIED_C),
    ("Half-price grocery", game_text(43_200), VERIFIED_C),
    ("Collectible", "3 in 6,600 each frame", VERIFIED_C),
    ("House malfunction", "1 in 800 every 2 real seconds, also while paused", VERIFIED_E),
    ("Autosave", "every 10 real minutes", VERIFIED_C),
    ("Day and night", "your PC's clock", VERIFIED_C),
)


def _index() -> list[Fact]:
    g, C, U = INDEX, VERIFIED_C, UNCONFIRMED
    facts = [Fact(g, "Timers (real time):", C)]
    facts += [Fact(g, f"{name}: {length}.", label, sub=True) for name, length, label in _TIMERS]
    facts += [
        Fact(g, "The game has 5,088 places that roll a random number; 5,087 are in code the game reaches. The gameplay ones are on "
                "this page: hunger, eating, waste, starvation, sickness, recovery, old age, conception, twins, "
                "careers, work, events, the dating candidate, messes, collectibles and malfunctions.", C),
        Fact(g, "4,492 of them are in the family members' 217 actions (how long an action lasts, which variant, "
                "where they walk). What those actions give was not decoded.", U),
        Fact(g, "The rest are setup, looks, names, the screen and input; the two largest groups (58 and 57 rolls) "
                "were not decoded.", U),
    ]
    return facts


def facts() -> list[Fact]:
    """Every line of the page, in GROUPS order."""
    out = (_time() + _needs() + _health() + _sickness() + _old_age() + _babies() + _careers() + _money()
           + _leaving() + _marriage() + _events() + _messes() + _collectibles() + _malfunctions() + _index())
    return sorted(out, key=lambda f: GROUPS.index(f.group))      # stable: the order within a group is kept


def line(fact: Fact) -> str:
    """A fact as it reads on the page: the bullet, the words, then its label."""
    return f"{SUB_BULLET if fact.sub else BULLET}{fact.text}  {fact.label}"


def render(page: list[Fact] | None = None) -> str:
    """The whole page as text: the intro notes, then each group's heading and lines."""
    page = facts() if page is None else page
    parts = [INTRO, LABEL_NOTE, SPEED_NOTE]
    for group in GROUPS:
        lines = [line(f) for f in page if f.group == group]
        if lines:
            parts.append(group + "\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# The window (opened from the Tools tab)
# ---------------------------------------------------------------------------

LABEL_COLOURS = {VERIFIED_E: "#1b6e20", VERIFIED_C: "#245a9a", UNCONFIRMED: "#b00020"}
WIDTH, HEIGHT = 900, 720
MIN_WIDTH, MIN_HEIGHT = 600, 500
LINKS_PER_ROW = 4


def open_window(parent, link_factory=None):
    """The Game Mechanics window: links to each group at the top, then the page in a read-only text box with
    its own scroll bar.  `link_factory(parent, text, command)` makes a link (the patcher's own link look);
    without it a plain button is used.  Returns the Toplevel."""
    import tkinter as tk
    from tkinter import ttk

    window = tk.Toplevel(parent)
    window.title(TITLE)
    window.geometry(f"{WIDTH}x{HEIGHT}")
    window.minsize(MIN_WIDTH, MIN_HEIGHT)
    outer = ttk.Frame(window, padding=12)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=INTRO, wraplength=WIDTH - 60, justify="left").pack(anchor="w")
    links = ttk.Frame(outer)
    links.pack(anchor="w", fill="x", pady=(8, 8))
    body = ttk.Frame(outer)
    body.pack(fill="both", expand=True)
    text = tk.Text(body, wrap="word", padx=8, pady=8, borderwidth=1, relief="solid", font=("Segoe UI", 10))
    bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    text.tag_configure("heading", font=("Segoe UI", 12, "bold"), spacing1=10, spacing3=4)
    text.tag_configure("note", foreground="#555555", spacing3=6)
    text.tag_configure("sub", lmargin1=24, lmargin2=40)
    text.tag_configure("bullet", lmargin1=4, lmargin2=16)
    for label, colour in LABEL_COLOURS.items():
        text.tag_configure(label, foreground=colour, font=("Segoe UI", 9, "bold"))

    for note in (LABEL_NOTE, SPEED_NOTE):
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
            words = (SUB_BULLET if fact.sub else BULLET) + fact.text + "  "
            text.insert("end", words, "sub" if fact.sub else "bullet")
            text.insert("end", fact.label, (fact.label, "sub" if fact.sub else "bullet"))
            text.insert("end", "\n", "sub" if fact.sub else "bullet")
    text.configure(state="disabled")             # read-only: the page can be selected and copied, not edited

    def jump(group: str) -> None:
        text.see("end")
        text.see(f"group:{group}")

    for n, group in enumerate(GROUPS):
        if link_factory is not None:
            link = link_factory(links, group, lambda g=group: jump(g))
        else:
            link = ttk.Button(links, text=group, command=lambda g=group: jump(g))
        link.grid(row=n // LINKS_PER_ROW, column=n % LINKS_PER_ROW, sticky="w", padx=(0, 18), pady=1)

    close = ttk.Button(outer, text="Close", command=window.destroy)
    close.pack(anchor="e", pady=(8, 0))
    window.bind("<Escape>", lambda _event: window.destroy())
    window.text = text                         # for the tests
    return window


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
