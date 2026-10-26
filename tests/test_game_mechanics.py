"""Game Mechanics (patcher/vf1_game_mechanics.py and its Tools-tab window).

The page is VF1's own facts only (docs/game-mechanics/spec.md and the re-checks of 2026-10-25), each line with its
evidence label beside it, in family words, real times at Normal with Slow and Fast beside them. The window only
reads: no save, game file or install is opened or written.
"""
import json
import re
from pathlib import Path

import pytest

import vf1_game_mechanics as gm
from test_tools_tab import app, documents, save, snapshot, text_of, tk_root, walk  # noqa: F401 -- fixtures

ROOT = Path(__file__).resolve().parents[1]
PAGE = gm.render()
FACTS = gm.facts()


def texts(group=None):
    return [f.text for f in FACTS if group is None or f.group == group]


def find(pattern, group=None):
    hits = [f for f in FACTS if (group is None or f.group == group) and re.search(pattern, f.text)]
    assert hits, pattern
    return hits


# ------------------------------------------------------------------ the page


def test_every_line_carries_its_label_beside_it():
    assert FACTS
    for fact in FACTS:
        assert fact.label in (gm.VERIFIED_E, gm.VERIFIED_C, gm.UNCONFIRMED)
        assert gm.line(fact).endswith("  " + fact.label)
        assert gm.line(fact) in PAGE
    assert {f.label for f in FACTS} == set(gm.LABELS)


def test_a_fact_with_an_unknown_label_or_group_is_refused():
    with pytest.raises(ValueError):
        gm.Fact(gm.TIME, "x", "VERIFIED")
    with pytest.raises(ValueError):
        gm.Fact("Weather", "x", gm.VERIFIED_C)


def test_every_group_has_lines_and_they_come_in_order():
    seen = [f.group for f in FACTS]
    assert [g for g in gm.GROUPS if g in seen] == list(gm.GROUPS)
    assert seen == sorted(seen, key=gm.GROUPS.index)
    for group in gm.GROUPS:
        assert f"\n\n{group}\n{gm.BULLET}" in PAGE
    assert not FACTS[0].sub


def test_family_words_and_no_virtual_villagers_systems():
    lowered = PAGE.lower().replace("my weather machine", "")       # a VF1 e-mail's own title
    for label, _on in gm.PATCH_SETTINGS.values():                  # the patcher's own setting names, as it shows them
        lowered = lowered.replace(label.lower(), "")
    for word in ("villager", "tribe", "village", "island", "weather", "mushroom", "tech point", "god power",
                 "heathen", "faith", "puzzle", "golden child"):
        assert word not in lowered, word
    assert "family member" in lowered


def test_the_notes_explain_the_labels_and_the_speeds():
    for label in gm.LABELS:
        assert label in gm.LABEL_NOTE
    assert "Normal" in gm.SPEED_NOTE and "Slow" in gm.SPEED_NOTE and "Fast" in gm.SPEED_NOTE
    assert PAGE.startswith(gm.INTRO + "\n\n" + gm.PATCHER_NOTE + "\n\n" + gm.LABEL_NOTE + "\n\n" + gm.SPEED_NOTE)


def test_real_times_follow_the_speed_divisor():
    assert (gm.SLOW, gm.NORMAL, gm.FAST) == (20, 10, 5)
    assert [gm.unit_seconds(1, s) for s in (gm.SLOW, gm.NORMAL, gm.FAST)] == [1200, 600, 300]
    assert [gm.game_seconds(3600, s) for s in (gm.SLOW, gm.NORMAL, gm.FAST)] == [7200, 3600, 1800]
    assert gm.duration(31_000) == "8 hours 36 minutes 40 seconds"
    assert gm.duration(90) == "1 minute 30 seconds"
    assert gm.units_text(20) == "3 hours 20 minutes on Normal, 6 hours 40 minutes on Slow, 1 hour 40 minutes on Fast"


def test_time_away_is_the_emulated_clamp_counted_at_normal():
    away = " ".join(f.text for f in FACTS if f.group == gm.TIME and f.label == gm.VERIFIED_E)
    for words in ("up to 8 hours 36 minutes 40 seconds (31,000 seconds) away: counted in full",
                  "up to exactly 24 hours: counted as 8 hours 36 minutes 40 seconds",
                  "more than 24 hours: counted as 24 hours (144 age units, 7.2 years)",
                  "in full up to 6 hours 36 minutes 40 seconds", "in full up to 10 hours 36 minutes 40 seconds"):
        assert words in away
    find(r"never reach a save: the game saves a family at Normal", gm.TIME)


def test_a_paused_clock_stops():
    assert find(r"^Paused: the game clock stops", gm.TIME)[0].label == gm.VERIFIED_C
    assert find(r"^Paused: nobody ages, and the paused time is never added", gm.TIME)[0].label == gm.VERIFIED_E
    assert "99.9" not in PAGE and "1/100" not in PAGE
    find(r"Paused, none come", gm.EVENTS)
    find(r"Paused, no interest builds up", gm.MONEY)


def test_the_owners_checks_that_held_are_shown_as_the_games_own_behaviour():
    interest = find(r"Interest has no limit on missed days", gm.MONEY)[0]
    assert interest.label == gm.VERIFIED_E and "$10,000" in interest.text
    paused = find(r"also while the game is paused", gm.MALFUNCTIONS)[0]
    assert paused.label == gm.VERIFIED_E and "41 in 32,768" in paused.text


def test_the_owners_checks_that_failed_are_left_out():
    lowered = PAGE.lower()
    assert "cannot kill" not in lowered and "can't kill" not in lowered
    assert "fifth" not in lowered and "counted as 5" not in lowered
    # what the game does instead: a starving family member dies through the health check, as Unknown causes
    starving = find(r"A starving family member still dies", gm.HEALTH)[0]
    assert starving.label == gm.VERIFIED_E and "Unknown causes" in starving.text
    assert find(r"for a family member with a career: each active group", gm.NEEDS)[0].label == gm.VERIFIED_E


def test_the_extra_food_group_without_a_career_is_shown_as_emulated():
    assert "Grains" in gm.EXTRA_GROUP and "even after those Grains run out" in gm.EXTRA_GROUP
    assert "any food group" not in gm.EXTRA_GROUP.lower()
    old = [f for f in FACTS if f.group == gm.OLD_AGE and f.text.startswith(gm.EXTRA_GROUP)]
    ill = [f for f in FACTS if f.group == gm.SICKNESS and f.text.startswith(gm.EXTRA_GROUP)]
    assert len(old) == len(ill) == 1
    assert old[0].label == ill[0].label == gm.VERIFIED_E
    assert "10.01% without a career against 20.02% with one" in old[0].text
    assert "0.504% / 0.453% / 0.035% / 0.015%" in ill[0].text
    # the tables still say they are for a family member with a career
    find(r"^Chance of dying on a birthday, for a family member with a career", gm.OLD_AGE)
    find(r"for a family member with a career \(any sickness", gm.SICKNESS)
    find(r"as counted for a family member with a career", gm.NEEDS)


def test_unconfirmed_lines_say_what_is_not_known():
    for pattern in (r"Which label sits beside which bar", r"symptoms' names", r"Which cause the game shows",
                    r"How often a family member goes to work", r"Which of the three career rooms",
                    r"What the game calls leaving home", r"Whether game time .* while the game is closed"):
        assert find(pattern)[0].label == gm.UNCONFIRMED, pattern


def test_the_careers_match_the_spec_table():
    rows = [line.split("\t") for line in
            (ROOT / "docs" / "game-mechanics" / "careers.tsv").read_text(encoding="utf-8").splitlines()[1:]]
    assert len(gm.CAREER_LIST) == len(rows) == 108
    for career, row in zip(gm.CAREER_LIST, rows):
        assert (career.id, career.room, career.name) == (int(row[0]), int(row[1]), row[2])
        assert career.salaries == tuple(int(x) for x in row[3:11])
    assert {c.room for c in gm.CAREER_LIST[:30]} == {1} and {c.room for c in gm.CAREER_LIST[30:79]} == {2}
    assert {c.room for c in gm.CAREER_LIST[79:]} == {3}
    listed = [f for f in FACTS if f.group == gm.CAREERS and f.sub]
    assert len(listed) == 108 and listed[0].text == "Pastry Designer (room 1): 30, 35, 43, 48, 56, 65, 78, 100."


def test_every_event_is_listed_once():
    numbers = []
    for title, _kind, _effect, label in gm._EVENTS:
        assert label in gm.LABELS
        for a, b in re.findall(r"\b(\d+) to (\d+)\b", title):
            numbers += range(int(a), int(b) + 1)
        title = re.sub(r"\b\d+ to \d+\b", "", title)
        numbers += [int(n) for n in re.findall(r"(?<![$\w])(\d+)\b", title)]
    assert sorted(numbers) == list(range(1, 72))


def test_the_old_age_table_is_the_rule():
    for groups in range(5):
        line = find(rf"^{groups} food groups?: ", gm.OLD_AGE)[0].text
        # safe age 55 + groups; 10% per year over, so 10% one year past it, 100% ten years past
        assert line.startswith(f"{groups} food group") and f": {56 + groups} / {60 + groups} / {65 + groups}." in line


def test_the_module_only_reads():
    source = (ROOT / "patcher" / "vf1_game_mechanics.py").read_text(encoding="utf-8")
    for call in (r"\bopen\(", r"write_bytes", r"write_text", r"\.unlink\(", r"shutil", r"subprocess", r"os\.remove",
                 r"import vf1_save", r"vf1_save_backup"):
        assert re.search(call, source) is None, call


def test_printing_the_page(capsys):
    assert gm.main() == 0
    assert capsys.readouterr().out == PAGE


# ------------------------------------------------------------------ the game with the patcher


def patched(group=None):
    return [f for f in FACTS if gm.PATCHER_PREFIX in f.text and (group is None or f.group == group)]


def pin(group, *words):
    """the one "With the patcher" line in `group` holding every one of `words`; returns it"""
    hits = [f for f in patched(group) if all(w in f.text for w in words)]
    assert len(hits) == 1, (group, words, [f.text for f in patched(group)])
    return hits[0]


def test_the_page_says_it_is_the_unpatched_game_with_the_patchers_changes_beside_it():
    assert "describes the game without the patcher" in gm.PATCHER_NOTE
    assert '"With the patcher"' in gm.PATCHER_NOTE and "on by default" in gm.PATCHER_NOTE
    assert gm.PATCHER_NOTE in PAGE


def test_every_named_setting_is_the_manifests_label_and_default():
    manifest = json.loads((ROOT / "patcher" / "manifest.json").read_text(encoding="utf-8-sig"))
    settings = {s["id"]: (s["label"], s["default"]) for s in manifest["settings"]}
    for key, (label, on) in gm.PATCH_SETTINGS.items():
        assert settings[key] == (label, on), key
    assert gm.setting("UpTo28Children") == "Up to 28 Children, off by default"
    assert gm.setting("ClampMoneyAndFood") == "Clamp Max Money and Food, on by default"


def test_every_patcher_line_names_its_setting_and_is_verified():
    named = [f"({gm.setting(k)}" for k in gm.PATCH_SETTINGS] + [f"; {gm.setting('SpecialUpgrades')})"]
    lines = patched()
    assert len(lines) == 30
    for fact in lines:
        assert fact.text.startswith(gm.PATCHER_PREFIX), fact.text
        assert any(n in fact.text for n in named), fact.text
        assert fact.label in (gm.VERIFIED_E, gm.VERIFIED_C), fact.text
    # the old UNCONFIRMED "patcher upgrades" lines are gone: every upgrade is now a verified line
    assert "The patcher's" not in PAGE
    for name in ("Brokerage Account", "Food Club", "Health Plan", "Lucky Rock", "Maid", "Gardener", "Roll the Dice"):
        assert any(name in f.text for f in lines), name
        assert not any(name in f.text and f.label == gm.UNCONFIRMED for f in FACTS), name


def test_autosave_line_and_the_adopt_save():
    # AutoSaveGame 0x423920, from theGame::GameUpdate every frame: 600 s on the PC clock, no pause check,
    # SaveCurrentGame writes the slot file a quit writes (spec section 17, emulated)
    [stock] = find(r"^Autosave: every 10 real minutes, also while paused, to the same save file a quit writes\.$",
                   gm.INDEX)
    assert stock.sub and stock.label == gm.VERIFIED_E
    adopt = pin(gm.INDEX, "also a save right after you adopt (Fix Vanilla Game Bugs, on by default)",
                "the 10-minute autosave is unchanged")
    assert adopt.sub and adopt.label == gm.VERIFIED_C


def test_time_controls_and_time_warp():
    assert find(r"^Game speed: the game only ever runs at Normal\.$", gm.TIME)[0].label == gm.VERIFIED_C
    speeds = pin(gm.TIME, "(Cheat Upgrades, on by default)", "Slow (half speed), Fast (double speed), 5x and 10x")
    assert speeds.sub and speeds.label == gm.VERIFIED_C
    assert pin(gm.TIME, "never reach a save", "loads any other saved speed as Normal").label == gm.VERIFIED_C
    warp = pin(gm.TIME, "Time Warp", "61 age units (3 years and 1 unit)", "past the time-away limits",
               "stops at $750 more", "works while paused too")
    assert warp.label == gm.VERIFIED_E


def test_food_wraps_without_the_clamp_and_is_held_with_it():
    find(r"never goes below 0 when food is taken away and has no top limit", gm.NEEDS)
    find(r"only changes through eating, bags and events - there is no daily use", gm.NEEDS)
    wrap = find(r"^Food added past 2,147,483,647 wraps round", gm.NEEDS)[0]
    assert wrap.label == gm.VERIFIED_E and "-2,147,483,546" in wrap.text and gm.PATCHER_PREFIX not in wrap.text
    clamp = pin(gm.NEEDS, "(Clamp Max Money and Food, on by default)", "put back to 2,147,483,647")
    assert clamp.label == gm.VERIFIED_E and clamp.sub
    money = pin(gm.MONEY, "(Clamp Max Money and Food, on by default)", "$4,000,000,000", "no top limit")
    assert money.label == gm.VERIFIED_E


def test_food_club():
    deliveries = pin(gm.NEEDS, "Food Club", "+500 food and all four food groups", "once a game day",
                     "every missed game day is delivered at once", "500, 1,000, 15,000 and 50,000 food")
    assert deliveries.label == gm.VERIFIED_E and "(a Special Upgrade, $10,000" in deliveries.text
    assert "Add visible mobile version purchases, on by default" in deliveries.text
    guard = pin(gm.NEEDS, "Food Club", "less than 60 food", "60 food is added first", "30 food becomes 87")
    assert guard.label == gm.VERIFIED_E and guard.sub
    prices = pin(gm.MONEY, "Food Club", "cost half, rounded down", "$20 for $10", "$160 for $80")
    assert prices.label == gm.VERIFIED_E


def test_bank_and_store_upgrades():
    find(r"^Interest: 10% of the money a game day", gm.MONEY)
    brokerage = pin(gm.MONEY, "Brokerage Account", "11% a game day ($110 on $1,000)", "drops the rate to 1%",
                    "adds 2 points, up to 11%")
    assert brokerage.label == gm.VERIFIED_E and "$10,000" in brokerage.text
    cheat = pin(gm.MONEY, "(Cheat Upgrades, on by default)", "from 1% to 11% for every family",
                "5% pays $50 on $1,000, also with the Brokerage Account")
    assert cheat.label == gm.VERIFIED_E
    health = pin(gm.MONEY, "Health Plan", "cost a quarter, rounded down", "Penicillin $45 for $11",
                 "Baby Boost $500 for $125", "Doctor Consultation $175 for $43")
    assert health.label == gm.VERIFIED_E


def test_older_villager_mortality_curve():
    find(r"^No family member can live past 75\.$", gm.OLD_AGE)        # the stock rule stays
    curve = pin(gm.OLD_AGE, "(Older Villager Mortality Curve, on by default)", "less the food groups counted (at most 4)",
                "Air Purifier, the Bathroom Upgrade and health over 90 no longer count", "0.37% at 56",
                "3.59% at 65", "7.04% at 75", "15.15% at 100", "18.19% at 110", "23.23% at 111", "56.71% at 120",
                "93.59% at 150", "99.73% at 200")
    assert curve.label == gm.VERIFIED_E and not curve.sub
    top = pin(gm.OLD_AGE, "no top age", "1 birthday roll in 32,768 is survived")
    assert top.label == gm.VERIFIED_E


def test_allow_older_pregnancies_and_the_failed_try_wait():
    find(r"^mother over 50: 0%\.$", gm.BABIES)                         # the stock table stays
    older = pin(gm.BABIES, "(Allow Older Pregnancies, on by default)", "without the mother-over-50 cut-off",
                "at most 10.07% at 50", "5.04% at 55", "1.01% at 59", "0.91% at 60", "0.10% from 68",
                "never below 0.10%", "father 50 71.06% without the patch, 10.07% with it", "father 60 69.06% and 0.91%")
    assert older.label == gm.VERIFIED_E
    wait = pin(gm.BABIES, "no wait after a failed try", "(Allow Older Pregnancies, on by default)",
               "six children already, or a same-sex couple (Private Adult Romantic Time, on by default)")
    assert wait.label == gm.VERIFIED_E and wait.sub
    index = pin(gm.INDEX, "none after a failed try", "(Private Adult Romantic Time, on by default)")
    assert index.label == gm.VERIFIED_E


def test_up_to_28_children():
    find(r"Needs free child places \(6 children per generation\)", gm.BABIES)
    find(r"^At most 6 children per generation", gm.MARRIAGE)
    places = pin(gm.BABIES, "(Up to 28 Children, off by default)", "experimental", "28 child places per generation")
    limit = pin(gm.MARRIAGE, "(Up to 28 Children, off by default)", "at most 28 children per generation",
                "family tree still holds only the first 6")
    assert places.label == limit.label == gm.VERIFIED_E


def test_marriage_and_next_generation():
    find(r"Each candidate is the opposite sex", gm.MARRIAGE)
    same = pin(gm.MARRIAGE, "(Cheat Upgrades, on by default)", "Enable Same-Sex Marriage", "same sex as the head")
    nextgen = pin(gm.MARRIAGE, "(Allow Older Pregnancies, on by default)", "with no death",
                  "oldest family member at home is 60 or older")
    assert same.label == nextgen.label == gm.VERIFIED_E


def test_roll_the_dice():
    dice = pin(gm.EVENTS, "(Roll the Dice, on by default)", "costs $500", "pop-up event at once",
               "the $500 is given back")
    assert dice.label == gm.VERIFIED_C and not dice.sub


def test_maid_gardener_and_lucky_rock():
    maid = pin(gm.MESSES, "Maid", "every game hour (1 hour on Normal", "daytime only",
               "every sock, candy wrapper, cobweb and dirt smudge", "at night is skipped")
    garden = pin(gm.MESSES, "Gardener", "every weed in the yard")
    assert maid.label == garden.label == gm.VERIFIED_E and "$1,000" in maid.text
    find(r"3 in 6,600 chance", gm.COLLECTIBLES)
    find(r"rare 4\.00%, uncommon 13\.01%", gm.COLLECTIBLES)
    rate = pin(gm.COLLECTIBLES, "Lucky Rock", "3 in 3,300 chance")
    rarity = pin(gm.COLLECTIBLES, "Lucky Rock", "rare 8.01%, uncommon 26.03%, common 65.97%")
    assert rate.label == rarity.label == gm.VERIFIED_E and "$77,777" in rate.text
    for words in (("Lucky Rock", "Collectible: 3 in 3,300 each frame"), ("Maid's visit", "daytime only"),
                  ("Gardener's visit",), ("Food Club delivery", "every missed day delivered")):
        assert pin(gm.INDEX, *words).label == gm.VERIFIED_E


# ------------------------------------------------------------------ the window


def test_game_mechanics_is_on_the_tools_tab_with_a_question_mark(app):
    tools = app.root.nametowidget(app.sections.tabs()[1])
    assert "Game Mechanics..." in text_of(tools) and "game_mechanics" in app.help_keys


def test_the_window_shows_the_page_read_only_and_changes_no_file(app, save):
    before = snapshot(save)
    window = app.game_mechanics()
    app.root.update_idletasks()
    assert window.title() == gm.TITLE
    text = window.text
    assert str(text.cget("state")) == "disabled"
    shown = text.get("1.0", "end")
    for group in gm.GROUPS:
        assert f"\n{group}\n" in shown
        assert text.index(f"group:{group}")
    assert gm.PATCHER_NOTE in shown
    for fact in FACTS:
        assert gm.line(fact).strip() in shown
    for label in gm.LABELS:
        assert text.tag_ranges(label), label
    links = [w.cget("text") for w in walk(window) if w.winfo_class() == "TLabel"]
    assert all(group in links for group in gm.GROUPS)
    assert app.game_mechanics() is window                 # one window: asking again brings it forward
    assert snapshot(save) == before
    window.destroy()


def test_a_topic_link_scrolls_to_its_group_and_close_closes(app):
    window = app.game_mechanics()
    window.update()
    link = next(w for w in walk(window) if w.winfo_class() == "TLabel" and w.cget("text") == gm.INDEX)
    link.event_generate("<Button-1>")
    window.update()
    top = window.text.index("@0,0")
    assert float(top) > 2.0
    assert window.bind("<Escape>")
    next(w for w in walk(window) if w.winfo_class() == "TButton" and w.cget("text") == "Close").invoke()
    window.update()
    assert not window.winfo_exists()
    again = app.game_mechanics()
    assert again is not window and again.winfo_exists()
    again.destroy()


def test_the_window_ships_with_the_patcher():
    source = (ROOT / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert '"vf1_game_mechanics.py"' in source
