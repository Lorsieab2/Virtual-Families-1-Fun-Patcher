"""Game Mechanics (patcher/vf1_game_mechanics.py and its Tools-tab window).

The page is VF1's own facts only (docs/game-mechanics/spec.md and the re-checks of 2026-10-25), each line with its
evidence label beside it, in family words, real times at Normal with Slow and Fast beside them. The window only
reads: no save, game file or install is opened or written.
"""
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
    for word in ("villager", "tribe", "village", "island", "weather", "mushroom", "tech point", "god power",
                 "heathen", "faith", "puzzle", "golden child"):
        assert word not in lowered, word
    assert "family member" in lowered


def test_the_notes_explain_the_labels_and_the_speeds():
    for label in gm.LABELS:
        assert label in gm.LABEL_NOTE
    assert "Normal" in gm.SPEED_NOTE and "Slow" in gm.SPEED_NOTE and "Fast" in gm.SPEED_NOTE
    assert PAGE.startswith(gm.INTRO + "\n\n" + gm.LABEL_NOTE + "\n\n" + gm.SPEED_NOTE)


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
                    r"What the game calls leaving home", r"Roll the Dice", r"Lucky Rock",
                    r"Whether game time .* while the game is closed"):
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
