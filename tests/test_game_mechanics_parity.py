"""Game Mechanics, the Virtual Families 2 parity groups (owner, 2026-10-27: "Vf1 should also get the same stuff as
vf2!!!"): Weather, Dropping a family member on things, Pets, Clothing and Hairstyles, Trophies and the heir, Actions,
the deeper Careers, Pregnancy and babies, Old age and death and Collectibles lines, the settled Random Events, and
the "not in Virtual Families 1" lines. The page lines are pinned here; the numbers they rest on are pinned against the
vanilla exe (those tests skip without VF1_VANILLA_DIR)."""
import re
import struct

import pytest

import vf1_game_mechanics as gm

FACTS = gm.facts()
PAGE = gm.render()
BASE = 0x400000


def texts(group):
    return [f.text for f in FACTS if f.group == group]


def find(pattern, group=None):
    hits = [f for f in FACTS if (group is None or f.group == group) and re.search(pattern, f.text)]
    assert hits, pattern
    return hits


# ------------------------------------------------------------------ the groups and the parity map

# Every group of the Virtual Families 2 page (src/vf2_game_mechanics.py, main af2cc46) and where this page covers it.
VF2_GROUPS = {
    "Time and ageing": gm.TIME, "Needs and upkeep": gm.NEEDS, "Health and sickness": gm.SICKNESS,
    "Old age": gm.OLD_AGE, "Pregnancy and babies": gm.BABIES, "Careers": gm.CAREERS,
    "Money and interest": gm.MONEY, "Leaving home": gm.LEAVING,
    "Dating, marriage and the next generation": gm.MARRIAGE, "Random Events": gm.EVENTS, "Weather": gm.WEATHER,
    "Messes and malfunctions": gm.MALFUNCTIONS, "Collectibles": gm.COLLECTIBLES,
    "The store: prices and buying": gm.STORE, "Food and Medicine": gm.STORE_MEDS, "Flea Market": gm.STORE_SPECIALS,
    "Special Upgrades": gm.PATCHER_SPECIAL, "Services": gm.STORE, "Home Renovation": gm.HOME,
    "Career upgrades": gm.CAREER_ROOMS, "Furniture and Accessories": gm.DROPS, "Pets": gm.PETS,
    "Clothing and Hairstyles": gm.CLOTHING, "Actions": gm.ACTIONS, "Chance and timer index": gm.INDEX,
}


def test_every_vf2_group_has_its_place_on_this_page():
    for vf2, ours in VF2_GROUPS.items():
        assert ours in gm.GROUPS and texts(ours), vf2
    for group in (gm.WEATHER, gm.DROPS, gm.PETS, gm.CLOTHING, gm.TROPHIES, gm.ACTIONS):
        assert f"\n\n{group}\n{gm.BULLET}" in PAGE, group
    assert gm.GROUPS.index(gm.WEATHER) == gm.GROUPS.index(gm.EVENTS) + 1


def test_the_not_in_virtual_families_1_lines():
    lines = [f for f in FACTS if gm.NOT_IN_VF1 in f.text]
    assert len(lines) == 19
    for fact in lines:
        assert fact.text.startswith("Virtual Families 2's "), fact.text
        assert fact.label == gm.VERIFIED_C, fact.text
    groups = {f.group for f in lines}
    for group in (gm.WEATHER, gm.PETS, gm.CLOTHING, gm.DROPS, gm.ACTIONS, gm.CAREERS, gm.BABIES, gm.EVENTS,
                  gm.MESSES, gm.COLLECTIBLES, gm.STORE, gm.HOME, gm.MONEY, gm.OLD_AGE, gm.LEAVING, gm.TROPHIES):
        assert group in groups, group
    for words in ("Foggy and Snowing", "Fog In a Bottle and Snow in a Bottle", "Petting the pet",
                  "limit of 2 missed game days", "132 careers", "Home Renovation", "Rockhound Certificate"):
        assert any(words in f.text for f in lines), words


def test_the_flea_market_is_the_owners_name_and_specials_is_said_once():
    assert gm.STORE_SPECIALS == "Store: Flea Market"
    assert PAGE.count("specials") == 1
    find(r"six more places hold the Flea Market \(the game's code calls these items the specials\)", gm.STORE)
    # the patcher's own page of the same name is always told apart
    for fact in FACTS:
        if fact.text.startswith(gm.PATCHER_PREFIX + " (Flea Market, on by default)"):
            assert "the patcher's Flea Market page" in fact.text, fact.text
    find(r"^The Flea Market \(six places\): every 4 hours real time", gm.STORE)


# ------------------------------------------------------------------ Weather


def test_weather_uses_the_owners_names_and_the_codes_lengths():
    assert gm.WEATHER_NAMES == ("Normal", "Sunny", "Raining", "Stormy")
    names = find(r"^The sky has four states", gm.WEATHER)[0].text
    for words in ("Normal (the code's sky 0: the plain sky", "Sunny (sky 1: the sun-beam effect, a grey tint with sun "
                  "beams)", "Raining (sky 2: rain)", "Stormy (sky 3: rain with lightning)"):
        assert words in names, words
    lengths = find(r"^Normal lasts 900 to 2,399 game seconds", gm.WEATHER)[0].text
    assert "15 minutes to 39 minutes 59 seconds real time on Normal" in lengths
    assert "360 to 719 (6 minutes to 11 minutes 59 seconds real time on Normal" in lengths
    assert "20.02% chance" in find(r"^The sky is not saved", gm.WEATHER)[0].text
    find(r"Sunny is never picked, so it is Raining or Stormy, 1 in 2 each", gm.WEATHER)
    bottles = " ".join(texts(gm.STORE_SPECIALS))
    assert "the sky turns Stormy" in bottles and "the sky turns Normal, the plain sky" in bottles


# ------------------------------------------------------------------ Actions


def test_every_registered_action_is_listed_with_its_paths():
    assert len(gm.ACTION_LIST) == gm.REGISTERED_ACTIONS == 316
    ids = [k for k, _, _ in gm.ACTION_LIST]
    assert len(set(ids)) == 316 and ids == sorted(ids) and ids[0] == 0 and ids[-1] == 0x151
    assert gm.ACTIONS_CHOSEN == 186
    acts = {k: (cap, outs) for k, cap, outs in gm.ACTION_LIST}
    assert acts[0x2A] == ("Relaxing in the hammock", ("dirtiness +4, a happiness trend of +1, energy +2",
                                                      "a happiness trend of -1"))
    assert acts[0x98] == ("Taking a nap", ("energy +7 to +11, dirtiness +2",))
    assert acts[0x129][1] == ("dirtiness +8, a happiness trend of +10, energy -8, hunger +5, a try for a baby",)
    assert acts[0x33][1] == ("energy -2, a piece of career work, dirtiness +1, energy -2, hunger +1",)
    assert acts[0xC3] == ("Studying on the patio", ("energy -3, a happiness trend of +2, hunger +2",))
    assert acts[0xB1][0] == "Washing hands / Washing face" and acts[1][0] == "Testing bevmac chunk"
    assert sum(1 for _, cap, _ in gm.ACTION_LIST if not cap) == 16
    page = " ".join(texts(gm.ACTIONS))
    assert "“Going to bed” (7 actions): dirtiness +2, energy +5." in page
    assert "The game registers 316 actions" in page


# ------------------------------------------------------------------ drops, pets, clothing, trophies


def test_the_drop_targets():
    assert len(gm._DROPS) == 38
    page = " ".join(texts(gm.DROPS))
    for words in ("the hammock: Relaxing in the hammock.", "the refrigerator: Looking for snacks.",
                  "the bathroom sinks: Getting a drink of water, Brushing teeth",
                  "DEAD (never runs): one more drop code", "dropping a family member on the pet starts nothing"):
        assert words in page, words


def test_pets_and_clothing():
    assert "Pet Cat, Pet Dog and Pet Turtle, $500 each" in texts(gm.PETS)[0]
    find(r"nothing to any need, skill or stat", gm.PETS)
    find(r"^Clothes: a family member's body picture, one of 50", gm.CLOTHING)
    find(r"^Hairstyles: part of the head picture", gm.CLOTHING)


def test_every_trophy_is_listed_and_the_dead_one_is_marked():
    assert len(gm.TROPHY_LIST) == 101
    assert [k for k, _, _, _ in gm.TROPHY_LIST] == list(range(101))
    named = {k: (t, n) for k, t, _, n in gm.TROPHY_LIST}
    assert named[60] == ("The shed", 1) and named[23] == ("Praising good behavior", 9)
    assert named[92] == ("Trophy collector", 11) and named[100] == ("The impossible dream", 100)
    dead = find(r"^DEAD \(never won in play\): “It's not a pyramid but", gm.TROPHIES)[0]
    assert dead.label == gm.VERIFIED_C
    find(r"^The trophy is “The shed”", gm.KEYS)
    find(r"^The heir: ", gm.TROPHIES)


# ------------------------------------------------------------------ the deeper lines


def test_careers_pay_per_hour_of_game_time():
    listed = [f for f in FACTS if f.group == gm.CAREERS and "per hour of game time as a Beginner" in f.text]
    assert len(listed) == 108
    assert "BBQ Sauce Creator (room 1): $1.25 per hour of game time as a Beginner, $57.5 as a Master" in \
        listed[2].text
    find(r"one piece for every 400 of the weight of their room's Working on career action", gm.CAREERS)
    find(r"Its weight starts at 500", gm.CAREERS)


def test_the_baby_wait_twins_and_the_try():
    assert gm._twins((0,)) == [(0, "92.99%", "5.25%", "1.75%")]
    assert gm._twins((30,)) == [(30, "62.96%", "16.65%", "20.39%")]
    find(r"^B = 30 \(both parents at 100, the most\): single 62\.96%", gm.BABIES)
    find(r"10 minutes of real time with both at 80 or more, 1 hour 30 minutes with both 40 to 59", gm.BABIES)
    find(r"cut to 55 minutes from that moment \(real time\)", gm.BABIES)
    assert (gm._agree(5, 5), gm._agree(50, 50), gm._agree(94, 94)) == ("96.19%", "58.11%", "20.02%")
    find(r"^Family members never try for a baby on their own", gm.BABIES)


def test_every_death_cause_is_marked():
    causes = " ".join(texts(gm.OLD_AGE))
    for words in ("Unknown causes: reachable", "Old age: reachable", "DEAD (never recorded): Disease",
                  "DEAD (never recorded): Starvation", "DEAD (never recorded): Work accident and Act of Nature",
                  "No cause of death is ever shown"):
        assert words in causes, words


def test_the_settled_events():
    events = {f.text.split(":")[0]: f for f in FACTS if f.group == gm.EVENTS and f.sub}
    for title in ("7 Professional Network (Email Event)", "8 Professional Association Award (Email Event)",
                  "9 Infringement Complaint (Email Event)", "20 My Weather Machine (Email Event)",
                  "37 Earthquake (Popup Event)", "38 Aesthetic Society (Popup Event)",
                  "49 / 50 The Little Visitor (Popup Event)", "51 Small Package (Popup Event)",
                  "52 Medium Brown Box (Popup Event)", "53 Sealed Green Bag (Popup Event)",
                  "55 Scratch-Off Lottery Ticket (Popup Event)", "58 The Talent Scout (Popup Event)",
                  "63 The Mysterious Collector (Popup Event)", "69 Career Change Counselor (Popup Event)"):
        assert events[title].label in (gm.VERIFIED_E, gm.VERIFIED_C), title
    assert "more than $21" in events["55 Scratch-Off Lottery Ticket (Popup Event)"].text
    assert "33.03% of the time of $10 to $100" in events["55 Scratch-Off Lottery Ticket (Popup Event)"].text
    assert "+$500" in events["58 The Talent Scout (Popup Event)"].text
    assert "40.04% chance" in events["37 Earthquake (Popup Event)"].text
    assert not [f for f in FACTS if f.group == gm.EVENTS and f.label == gm.UNCONFIRMED]


def test_each_collectible_has_its_own_entry():
    items = [f for f in FACTS if f.group == gm.COLLECTIBLES and re.match(r"^(Old Coins|Nuts and Twigs|Bugs|Picture "
                                                                         r"Pieces), (common|uncommon|rare) \d", f.text)]
    assert len(items) == 48
    shares = gm._area_weights(True, True)
    assert round(sum(shares.values()), 9) == 1 and round(shares["Old Coins"], 4) == round(15668 / 32768, 4)
    assert gm._area_weights(False, False)["Bugs"] == 0 == gm._area_weights(False, False)["Picture Pieces"]
    assert items[0].text == "Old Coins, common 1: 9.920% / 16.299%."
    life = find(r"^How long one lasts: 2 minutes of real time", gm.COLLECTIBLES)[0].text
    assert "120 seconds on the save's real-time clock" in life
    find(r"^The full-set reward: no money and no item", gm.COLLECTIBLES)


# ------------------------------------------------------------------ the exe the numbers come from


@pytest.fixture(scope="module")
def exe(vanilla_dir):
    return (vanilla_dir / "Virtual Families.exe").read_bytes()


def at(exe, va, n):
    return exe[va - BASE:va - BASE + n]


def u32(exe, va):
    return struct.unpack_from("<I", exe, va - BASE)[0]


def test_the_trophy_table(exe):
    # rows of 24 bytes from 0x4E9518: id, target, 0x77, 0, title text, description text (title 0x1CE + 2k)
    for k, _title, _desc, target in gm.TROPHY_LIST:
        row = 0x4E9518 + 24 * k
        assert u32(exe, row) == k and u32(exe, row + 4) == target and u32(exe, row + 16) == 0x1CE + 2 * k, k


def test_the_sky_lengths_and_start(exe):
    # 0x492280: Normal 0x384 + rand(0x960 - 0x384), the others 0x168 + rand(0x2D0 - 0x168)
    assert at(exe, 0x49232E, 10) == bytes.fromhex("bf84030000b860090000")
    assert at(exe, 0x49233A, 10) == bytes.fromhex("bf68010000b8d0020000")
    # 0x4923B0: rand(100) < 20 -> the PC-minute sky 30 game seconds later
    assert at(exe, 0x4923C1, 2) == bytes.fromhex("6a64") and at(exe, 0x4923E3, 3) == bytes.fromhex("83f814")


def test_collectible_life_frames_and_areas(exe):
    assert at(exe, 0x414BCA, 3) == bytes.fromhex("83c078")             # GetSecondsFromGameStart + 120
    assert at(exe, 0x4080D0, 5) == bytes.fromhex("b8e8030000")         # frame length 1,000 / frame rate
    calls = (0x414401, 0x41442A, 0x41444F, 0x41447A, 0x41449B, 0x4144BC, 0x4144DD, 0x41450A, 0x41452D, 0x414556,
             0x41457F, 0x4145A0, 0x4145CB, 0x4145F4, 0x41461B, 0x41463F, 0x41466C, 0x414695, 0x4146BC, 0x4146E3,
             0x41470A, 0x41472F, 0x414758)
    assert len(calls) == len(gm._AREAS) == 23
    for va in calls:                                                    # each registers one area (0x413B00)
        assert exe[va - BASE] == 0xE8 and va + 5 + struct.unpack_from("<i", exe, va - BASE + 1)[0] == 0x413B00


def test_dialog_keys(exe):
    assert at(exe, 0x41CC00, 10) == bytes.fromhex("25360200000" "50c040000")   # Yes (0x40C) or OK (0x642)
    assert at(exe, 0x41EB2E, 3) == bytes.fromhex("83f801")             # purchase: command 1 closes, 3 buys
    assert at(exe, 0x40DA92, 8) == bytes.fromhex("817c2408e8030000")   # the name box lets only Esc through


def test_event_and_baby_numbers(exe):
    assert at(exe, 0x418C5A, 3) == bytes.fromhex("83f821") and at(exe, 0x418C5F, 2) == bytes.fromhex("6a0a")
    assert struct.unpack_from("<f", exe, 0x4B55B8 - BASE)[0] == 21.0          # Scratch-Off: more than $21
    assert struct.unpack_from("<f", exe, 0x4B55BC - BASE)[0] == -20.0
    assert struct.unpack_from("<d", exe, 0x4B2768 - BASE)[0] == 255.0         # Career Training: more than $255
    assert at(exe, 0x418352, 3) == bytes.fromhex("83f828")                    # Earthquake: rand(100) < 40
    assert at(exe, 0x441327, 5) == bytes.fromhex("05100e0000")                # the drop: an hour left ...
    assert at(exe, 0x44133E, 5) == bytes.fromhex("05e40c0000")                # ... cut to 55 minutes
    assert at(exe, 0x48724B, 2) == bytes.fromhex("6a69")                      # the agreement roll of 105
