"""Game Mechanics: the Family members group -- every person a chosen Virtual Families 1 save holds, one by one (the
owner approved the port of the Virtual Villagers Fun Patcher's per-villager group, 2026-11-26).

Each family member is one bullet -- their name, sex, age and health -- with sub-bullets for what else the save keeps
for them: being sick and an infection, the needs the Details screen shows (happiness, Fed, energy) and the hidden ones
(the happiness trend, dirtiness, the bathroom need), food groups, career, level, progress and salary, likes and
dislikes, "Wants kids?" and fertility, their place in the save's Family Tree (spouse, parents, children), a pregnancy,
and the whole name from the patcher's Names file.  Family members at home come first (oldest first), then those who
left home, then anyone who died whose body is still in the house.  Nothing is guessed: every value is a field of the
save, read with the patcher's own reader (vf1_save; the whole names through its Names file, vf1_names), and the
rules each value means are the ones the page's other groups state.

Where each value is in a villager record (gs+0xE790 + slot x 0x6B8; docs/vf1-save-format.md 2.4 and
docs/game-mechanics/spec.md section 19).  The record copies CVillagerState (villager +0x2AD4, 0x26 dwords, 0x48F760)
whole at +0xA8, so a state field +s is record +0xA8 + s; the Details screen's bars read the same villager fields
(patcher/vf1_art_meters.py: Happiness +0x2B0C, Fed 100 - hunger +0x2B14, Energy +0x2B08, Health +0x2AE0):
  +0xB4 health, +0xB8 cause of death, +0xCC age unit of conception, +0xD0 babies carried,
  +0xDC energy, +0xE0 happiness, +0xE4 happiness trend (-500..500), +0xE8 hunger, +0xEC dirtiness, +0xF0 bathroom
  need ("poo"), +0xF4 fertility, +0xF8 "Wants kids?",
  +0x104..+0x10A the seven symptoms: IsSick 0x48FD40 is "any of the seven bytes set" (an infection alone is not
  sick); +0x10C.. each symptom's end, a real-time stamp set to now + (rand(12) + 6) x 3,600 at 0x48FD80;
  +0x128 / +0x129 the mild and the serious infection (villager +0x2B54 / +0x2B55, set by UpdateDisease 0x4907B2 /
  0x4907C1);
  +0x12C..+0x12F the four food groups' flags (Grains, Dairy, Meats, Fruits and Veggies) and +0x130.. their ends, real
  time.  FoodGroupsActive 0x48FE30 counts five slots: a slot counts while its flag is set and its end is not before
  now (unsigned), and an ended slot's flag is cleared; the fifth slot's flag is the low byte of the Grains end and its
  end is the career id (-1, no career, never ends);
  +0x140 career, +0x144 level, +0x148 progress toward the next promotion (the Details screen's Progress bar, 3,000 at
  Master), +0x14C salary; +0x150 / +0x15C the likes and dislikes (3 places each, -1 empty), each an index into the
  game's own comma list, string 0x45B (likes) or 0x45C (dislikes), read by 0x481E20 / 0x481420 (LIKE_WORDS; the
  Family Tree's words for the same people match them, tests/test_game_mechanics_family.py).
A baby made in the house: the try's success (0x48EBA9) calls Impregnate 0x4864D0 with the father's name as the
literal "Joey" (0x4B7060) and the father's looks from the Patriarch (head +0x2A60, body +0x2A64), so the save never
keeps the father's own name: the page names him through the save's Family Tree (or, for a pregnancy, by those looks).
"Wants kids?" is 0x48FCC0: value / 10 picks No Way (0, 1), Not Really (2, 3), Maybe (4, 5), Would Be Nice (6, 7),
Definitely (8, 9, 10).

Read only: the save is read, never written.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import vf1_game_mechanics as gm
import vf1_save

GROUP = gm.FAMILY
C, E, U = gm.VERIFIED_C, gm.VERIFIED_E, gm.UNCONFIRMED

# Record offsets (see the module's docstring).
ENERGY, HAPPINESS, TREND, HUNGER, DIRTINESS, POO = 0xDC, 0xE0, 0xE4, 0xE8, 0xEC, 0xF0
SYMPTOMS, SYMPTOM_ENDS, MILD, SERIOUS = 0x104, 0x10C, 0x128, 0x129
GROUP_FLAGS, GROUP_ENDS = 0x12C, 0x130
CAREER, PROGRESS = 0x140, 0x148
FOOD_GROUPS = ("Grains", "Dairy", "Meats", "Fruits and Veggies")
# The Doctor Consultation's names for the seven symptoms (the Sickness group).
SYMPTOM_NAMES = ("hiccups", "a sore throat", "an upset stomach", "a headache", "a cough", "a skin rash",
                 "a blocked nose")
# String 0x45B (likes) and 0x45C (dislikes) of the stock exe: the same list, picked by place (0x481E20, 0x481420).
LIKE_WORDS = tuple(w.strip() for w in (
    "ants, crowds, resting, laundry, medicine, turnips, butterflies, flowers, bees, the dark, snakes, wind, rocks, "
    "heights, playing, exploring, blue, green, red, yellow, bushes, sand, sunlight, wood, crab meat, fish, fruit, "
    "flies, swimming, running, studying, dancing, birds, work, lifting, surprises, jokes, sleeping, jumping, cooking, "
    "eating, dreaming, talking, holidays, vegetables, quiet, clouds, dirt, plants, rain, fog, sitting, stories, "
    "thunder, lightning, stars, exercising, strolling, toys, insects, grass, spiders, roses, crickets, bathing, "
    "shaving, combing hair, makeup, flossing, brushing teeth, cleaning, loose socks, dusting, organizing, TV, "
    "Internet, spam, reading, technology, snacking, tools, computers, carbs, meat, milk, eggs, BBQ, burgers, pizza, "
    "sweets, pasta, soup, chocolate, peanut butter, soda, coffee, rice, bread, chicken, solitude, garbage, fixing, "
    "shopping, pinball, music, art, gophers").split(","))
WANTS_KIDS = ("No Way", "No Way", "Not Really", "Not Really", "Maybe", "Maybe", "Would Be Nice", "Would Be Nice",
              "Definitely", "Definitely", "Definitely")
ROOMS = {1: "the Kitchen", 2: "the Office", 3: "the Workshop"}
FATHER_STAND_IN = "Joey"            # 0x4B7060, the name every baby made in the house gets for its father
GROWN_UP = 360                      # 18 years: work, a try for a baby, marriage (the Careers and Pregnancy groups)
OLD = 1100                          # 55 years: IsNotOld 0x4897E0, the slower recovery and the birthday roll
PREGNANCY_UNITS = 21                # delivered on the unit after conception + 20 (Pregnancy and babies)
PROMOTION = 3000


@dataclass(frozen=True)
class Family:
    """A family save the window offers: its label and file."""
    label: str
    path: Path


def find_families(folders) -> list[Family]:
    """Every slot's save (Virtual Families1..5.ldw) in the save folders that the patcher can read, in folder then
    slot order.  Only reads."""
    out: list[Family] = []
    for folder in folders:
        for slot in range(1, 6):
            path = Path(folder) / f"{vf1_save.SAVE_PREFIX}{slot}.ldw"
            try:
                save = vf1_save.read_save(path)
            except (OSError, ValueError, struct.error):
                continue
            out.append(Family(f"Save {slot}: {save.family_name or '(no name)'} ({Path(folder).name})", path))
    return out


def _i32(raw: bytes, at: int) -> int:
    return struct.unpack_from("<i", raw, at)[0]


def _u32(raw: bytes, at: int) -> int:
    return struct.unpack_from("<I", raw, at)[0]


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def when(save: vf1_save.VF1Save, stamp: int) -> str:
    """A real-time stamp of the save (seconds from the family's start, the header's time) as your PC's local time."""
    moment = datetime.fromtimestamp(save.header.epoch + stamp)
    return f"{moment:%d %B %Y}, {moment:%H:%M}".lstrip("0")


def ages(units: int) -> str:
    """'41 years (827 age units; 13 more to the next birthday)'."""
    years = units // vf1_save.AGE_UNITS_PER_YEAR
    left = vf1_save.AGE_UNITS_PER_YEAR - units % vf1_save.AGE_UNITS_PER_YEAR
    return f"{_plural(years, 'year')} ({units:,} age units; {left} more to the next birthday)"


def stage(units: int) -> str:
    """The ages the game's own rules turn on (Careers, Pregnancy and babies, Old age and death)."""
    if units < GROWN_UP:
        return "a child: under 18, the age from which the game lets a family member work, marry and have a baby"
    if units < OLD:
        return "a grown-up (18 or older)"
    return "55 or older: old age is rolled on every birthday and recovery is slower (see Old age and death, Health)"


def like_text(places) -> str:
    words = [LIKE_WORDS[i] if 0 <= i < len(LIKE_WORDS) else f"(item {i}, not in the game's list)"
             for i in places if i != -1]
    return ", ".join(words) if words else "none"


def wants_kids(value: int) -> str:
    return WANTS_KIDS[min(10, max(0, value // 10))]


def food_groups(save: vf1_save.VF1Save, v: vf1_save.Villager) -> tuple[list[str], int]:
    """(the four groups' words, how many slots FoodGroupsActive counts) at the moment the family was saved."""
    raw, now = v.raw, save.time.saved_at
    words, counted = [], 0
    for k in range(5):
        flag = raw[GROUP_FLAGS + k]
        end = _u32(raw, GROUP_ENDS + 4 * k)
        live = bool(flag) and end >= now
        counted += live
        if k < 4 and flag:
            words.append(f"{FOOD_GROUPS[k]} until {when(save, end)}" + ("" if live else " (already over)"))
    return words, counted


def sick_words(save: vf1_save.VF1Save, v: vf1_save.Villager) -> str | None:
    raw = v.raw
    have = [k for k in range(7) if raw[SYMPTOMS + k]]
    infections = [w for at, w in ((MILD, "a mild infection (Penicillin cures it)"),
                                  (SERIOUS, "a serious infection (Vancomycin cures it)")) if raw[at]]
    if not have and not infections:
        return None
    parts = []
    if have:
        parts.append("sick with " + ", ".join(
            f"{SYMPTOM_NAMES[k]} (its time ends {when(save, _u32(raw, SYMPTOM_ENDS + 4 * k))}, real time"
            + (", already over when the family was saved" if _u32(raw, SYMPTOM_ENDS + 4 * k) < save.time.saved_at
               else "") + ")"
            for k in have))
    else:
        parts.append("not sick by the game's test (no symptom), but carries " + " and ".join(infections))
    if have and infections:
        parts.append("also " + " and ".join(infections))
    return "; ".join(parts)


def _tree_seat(save: vf1_save.VF1Save, v: vf1_save.Villager):
    """(seat words, (parent1, parent2) names from the save's Family Tree or None)."""
    rec = save.current_family
    if rec is None:
        return "", None
    if save.villager_for(rec.parent1) is v:
        if rec.generation > 1 and rec.parent1.parent_child_index >= 0:
            prev = save.family_records[rec.generation - 2]
            k = rec.parent1.parent_child_index
            if k < len(prev.children):
                return (f"the head of the family, generation {rec.generation} (the heir)",
                        (prev.parent1.name, prev.parent2.name))
        return f"the head of the family, generation {rec.generation}" + (
            " (the founder)" if rec.generation == 1 else ""), None
    if save.villager_for(rec.parent2) is v:
        return f"married into the family, generation {rec.generation}", None
    for child in rec.children:
        if save.villager_for(child) is v:
            return f"a child of generation {rec.generation}", (rec.parent1.name, rec.parent2.name)
    return "", None


def _parents_line(save, v, tree) -> str:
    own = (v.parent1_name, v.parent2_name)
    if tree is not None:
        text = f"Parents: {tree[0]} and {tree[1]} (the save's Family Tree)."
        if own != tree and any(own):
            text += (f" Their own record keeps \"{own[0]}\" and \"{own[1]}\"" + (
                f": \"{FATHER_STAND_IN}\" is the name the game writes for the father when a try "
                "for a baby works." if own[0] == FATHER_STAND_IN else "."))
        return text
    if not any(own):
        return "Parents: none in the save (a founder, an adopted child, or one the game made without parents)."
    text = f"Parents: their own record keeps \"{own[0]}\" and \"{own[1]}\"; the save's Family Tree does not list them."
    if own[0] == FATHER_STAND_IN:
        text += f" \"{FATHER_STAND_IN}\" is the name the game writes for the father when a try for a baby works."
    return text


def _children_line(save, v) -> str | None:
    rec = save.current_family
    if rec is None or v not in [save.villager_for(rec.parent1), save.villager_for(rec.parent2)]:
        return None
    words = []
    for child in rec.children:
        kid = save.villager_for(child)
        unborn = 0 <= child.slot < vf1_save.VILLAGER_SLOTS and child.slot in save.pending_babies
        state = ("on the way, not born yet" if unborn else "not in the house" if kid is None or not kid.present
                 else "died" if kid.dead
                 else "left home" if kid.left_home else "at home")
        words.append(f"{child.name} ({state})")
    named = {c.name for c in rec.children}
    more = [k.name for k in save.household() if k.name not in named and k is not v
            and v.name in (k.parent1_name, k.parent2_name) and not k.dead]
    text = ("Children in the save's Family Tree: " + ", ".join(words) if words
            else "Children in the save's Family Tree: none")
    if more:
        text += "; more in the house that name them as a parent: " + ", ".join(more)
    return text + "."


def _career_line(v) -> str:
    if v.career == -1:
        return "Career: none; no salary."
    if not 0 <= v.career < len(gm.CAREER_LIST) or not 0 <= v.career_level < len(gm.LEVELS):
        return f"Career: number {v.career} at level {v.career_level}, not one of the game's 108 careers and 8 levels."
    career = gm.CAREER_LIST[v.career]
    level = gm.LEVELS[v.career_level]
    table = career.salaries[v.career_level]
    text = (f"Career: {career.name} (career room {career.room}, {ROOMS.get(career.room, '')}), {level} (level "
            f"{v.career_level + 1} of 8); progress {v.skills_8:,} of {PROMOTION:,} toward the next promotion")
    text += f"; salary ${v.salary:,}: ${gm._hourly(v.salary)} per hour of game time (1 hour real time on Normal)"
    if v.salary != table:
        text += (f". The game's own table pays a {level} {career.name} ${table:,}: the save holds ${v.salary:,}, "
                 "and the save's value is the one paid")
    return text + "."


def _pregnancy_line(save, v) -> str | None:
    if not v.pregnant:
        return None
    babies = {1: "1 baby", 2: "twins", 3: "triplets"}.get(v.babies_carried, f"{v.babies_carried} babies")
    due = v.pregnant_since + PREGNANCY_UNITS
    left = max(0, due - v.age_processed)
    spouse = save.spouse_of(v.slot)
    father = (f"the father's looks are {spouse.name}'s" if spouse is not None and (v.pending_father_head,
              v.pending_father_body) == (spouse.head, spouse.body)
              else f"the father's looks: head {v.pending_father_head}, body {v.pending_father_body}")
    name = (f" (the save keeps the father's name as \"{v.pending_father_name}\", the name the game writes for the father when a "
            "try for a baby works)" if v.pending_father_name == FATHER_STAND_IN else
            f" (the save keeps the father's name as \"{v.pending_father_name}\")")
    return (f"Pregnant with {babies}, conceived at age unit {v.pregnant_since:,}: born on age unit {due:,}, "
            f"{_plural(left, 'age unit')} to go ({gm.units_text(left)}); {father}{name}.")


def _person(save, short: vf1_save.Villager, v: vf1_save.Villager) -> list[gm.Fact]:
    out: list[gm.Fact] = []

    def add(text: str, label: str = C, sub: bool = True) -> None:
        out.append(gm.Fact(GROUP, text, label, sub))

    raw = v.raw
    sex = {0: "Male", 1: "Female"}.get(v.sex, f"sex value {v.sex}")
    if v.dead:
        cause = vf1_save.DEATH_CAUSES_UNCONFIRMED.get(v.death_cause, f"cause {v.death_cause}")
        add(f"{v.name}: {sex}, died at {ages(v.age_units)}; health {v.health}; the cause the save keeps: {cause}. "
            "The body is still in the house (it is removed 240 age units after their last update; see Old age and "
            "death).", C, False)
        return out
    head = f"{v.name}: {sex}, {ages(v.age_units)}; health {v.health} of 100"
    sick = sick_words(save, v)
    head += ", sick" if sick and sick.startswith("sick") else ""
    add(head + ".", C, False)
    seat, tree = _tree_seat(save, v)
    add(("Left home: they stay in the save but never age or update again (see Leaving home); " if v.left_home else
         "At home; ") + f"{stage(v.age_units)}." + (f" In the save's Family Tree: {seat}." if seat else ""))
    if short.name != v.name:
        add(f"Whole name: {v.name}; the save keeps the short form \"{short.name}\" and the patcher's Names file "
            "the whole name (Virtual Families 1 Patcher Data\\Names).")
    if sick:
        add(sick[0].upper() + sick[1:] + ". See Sickness for what each does.")
    else:
        add("Not sick: no symptom and no infection.")
    hunger = _i32(raw, HUNGER)
    add(f"Details screen: Happiness {_i32(raw, HAPPINESS)}, Health {v.health}, Fed {100 - hunger} (100 less the "
        f"hunger, {hunger}), Energy {_i32(raw, ENERGY)} (the game keeps happiness, hunger and energy 1 to 100, "
        "health 0 to 100).")
    add(f"Hidden: happiness trend {_i32(raw, TREND):+,} (-500 to 500; see Needs and upkeep for how it moves "
        f"happiness), dirtiness {_i32(raw, DIRTINESS)}, bathroom need {_i32(raw, POO)} (at 90 or more it drops to 25 "
        "to 49).")
    groups, counted = food_groups(save, v)
    live = sum(1 for g in groups if not g.endswith("(already over)"))
    add("Food groups when the family was saved (each lasts 24 hours of real time; your PC's clock): "
        + (", ".join(groups) or "none") + f". The game counts {counted}"
        + (": one more than the groups, the extra one every family member without a career gets once they have had "
           "Grains (see Needs and upkeep)" if counted > live else "") + ".")
    n = v.name_index
    if n % 6 == 0:
        add(f"Name number {n}, a multiple of 6: with no food at all in the house the 1-health loss each age unit is "
            "certain, not 76.05% (see Health).")
    elif n % 2:
        add(f"Name number {n}, odd: with no food at all and health 20 or less, a 31.03% chance of +1 health each "
            "age unit (see Health).")
    add(_career_line(v))
    add(f"Likes: {like_text(v.likes)}. Dislikes: {like_text(v.dislikes)}.")
    add(f"Wants kids?: {v.wants_children} (\"{wants_kids(v.wants_children)}\", as the game words it); "
        f"fertility {v.fertility} of 100" + (f" ({v.fertility - 85} over 85, added to the twins and triplets "
                                            "chances)" if v.fertility > 85 else "") + ".")
    spouse = save.spouse_of(v.slot)
    if spouse is not None:
        add(f"Spouse: {spouse.name} (the save's Family Tree, generation {save.generation}).")
    add(_parents_line(save, v, tree))
    kids = _children_line(save, v)
    if kids:
        add(kids)
    pregnancy = _pregnancy_line(save, v)
    if pregnancy:
        add(pregnancy)
    return out


def facts_for(save: vf1_save.VF1Save, short: vf1_save.VF1Save) -> list[gm.Fact]:
    """The group for one save (`short` is the same save read without the Names file, for the short forms)."""
    out: list[gm.Fact] = []
    people = [(short.villagers[v.slot], v) for v in save.household()]
    home = [p for p in people if not p[1].dead and not p[1].left_home]
    left = [p for p in people if not p[1].dead and p[1].left_home]
    dead = [p for p in people if p[1].dead]
    saved = when(save, save.time.saved_at)
    out.append(gm.Fact(GROUP, (
        f"{save.family_name or '(no name)'}, generation {save.generation}, saved {saved} (your PC's clock): "
        f"{len(home)} at home, {len(left)} left home" + (f", {len(dead)} died with the body still in the house"
                                                         if dead else "")
        + ". Every value below is read from the save as it was written; the game moves them on from there. Ages count "
        "in age units (20 make a year; 1 age unit is 10 minutes of game time, 10 minutes real time on Normal); the "
        "times are real time."), C))
    for title, group in (("At home", home), ("Left home", left), ("Died", dead)):
        if not group:
            continue
        for short_v, v in sorted(group, key=lambda p: (-p[1].age_units, p[1].slot)):
            out += _person(save, short_v, v)
    unborn = [s for s in save.pending_babies if 0 <= s < vf1_save.VILLAGER_SLOTS]
    if unborn:
        out.append(gm.Fact(GROUP, f"Babies on the way: {len(unborn)}, kept hidden in the house until they are born "
                                  "(see Pregnancy and babies).", C))
    return out


def facts(path) -> list[gm.Fact]:
    """The Family members group for the save file `path` (one line saying why, when it cannot be read)."""
    try:
        data = Path(path).read_bytes()
        short = vf1_save.parse_save(data)
        save = vf1_save.read_save(path)
    except (OSError, ValueError, struct.error) as exc:
        return [gm.Fact(GROUP, f"This save could not be read: {exc}.", C)]
    return facts_for(save, short)
