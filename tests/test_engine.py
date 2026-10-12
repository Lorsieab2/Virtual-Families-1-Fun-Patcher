"""The ported apply / settings / restore engine (vf1_patcher.py)."""
import argparse
import json
from pathlib import Path

import pytest

import vf1_patcher as vp
from conftest import MANIFEST, ROOT, write_manifest

SPEC = {
    'FixVanillaGameBugs': ('Fix Vanilla Game Bugs',
        'Keeps a brand-new family if the game is closed without quitting (the original game only saved before the adoption). In the Power Failure event, choosing to keep the food now says the food was not ok when people really get sick (the original game always said it was fine). An age set by a cheat no longer becomes the Oldest Villager record: the record only rises when a villager ages into it.'),
    'OlderVillagerMortalityCurve': ('Older Villager Mortality Curve',
        "Replaces only the annual old-age death roll with a calibrated curve that accelerates past effective age 110. Active food groups still subtract 0-4 effective years. No hard maximum age."),
    'PrivateRomanticTime': ('Private Adult Romantic Time',
        'A married opposite-sex couple at six children can still have private romantic time when one is dropped on the other (the original game refuses with "They have enough kids already!"). Like the Virtual Families 2 patcher, a couple that cannot conceive (same-sex, or six children) is also never made to wait "It is too soon to try to make a baby again" after an attempt, and the action reads "Having private adult romantic time". No baby is possible for them.'),
    'AllowOlderPregnancies': ('Allow Older Pregnancies',
        'Optional patch: preserves normal fertility behavior below age 50, then allows a small pregnancy chance when either parent is 50 or older. The older parent caps the chance from 10.0% at age 50 down to a permanent 0.1% floor at age 69+. Failed attempts involving an age-50+ parent do not start the stock try-for-baby cooldown. The stock Next Generation flow also becomes available when the oldest living person reaches age 60, provided there is a surviving child.'),
    'ClampMoneyAndFood': ('Clamp Max Money and Food',
        "Keeps coins at no more than 4,000,000,000 and food at no more than 2,147,483,647, the Virtual Families 2 patcher's maximums (the original game has no limit, and food wraps to a negative number past 2,147,483,647, which glitches the game)."),
    'SpecialUpgrades': ('Add visible mobile version purchases',
        'Special Upgrades in the Upgrades menu: Brokerage Account, Food Club, Health Plan and Lucky Rock, as in the Virtual Families 2 patcher, plus a Maid and a Gardener who keep the house and yard clean.'),
    'CheatUpgrades': ('Cheat Upgrades',
        "Adds the Upgrades button's cheat pages: money, food, interest rate, villager cheats, store price multipliers, Anti-Spam Software ownership, achievements and collections, house and yard mess, time controls (pause; Slow, Normal and Fast as in Virtual Villagers, plus 5x and 10x; time warp), and the Family page (same-sex marriage, candidate reroll, divorce, pregnancy one-shots, spawned children, Adopt New Person after a game over, Evict Family), and a Clothing and Hairstyles page that shows every hairstyle and outfit and gives the one you click to a villager."),
    'FleaMarket': ('Flea Market',
        'Every tray item the store sells, to buy or get for free.'),
    'RollTheDice': ('Roll the Dice',
        '$500: an island event happens right away.'),
    'CustomMapImages': ('Custom Map/Game Images',
        'Replaces the standard house and some game images with customized ones. Credit to the original creators on LDWForums.'),
    'VF2Songs': ('VF1 + VF2 Songs',
        'Adds VF2 songs in addition to the normal VF1 songs.'),
    'GlowingCollectables': ('Glowing Collectables',
        'Makes the collectables in the yard glow, so they are easier to spot.'),
    'BehaviorLabelVariants': ('Behavior Label Variants',
        'Varies the caption shown for a villager\'s action, using the Virtual Families 2 patcher\'s own captions: Watching TV, Reading, Browsing the web, Playing video games, Playing a board game, Doing homework and taking an online test, the sandbox, watering the flower boxes, Taking a nap (dreams), Needs to sit down, Enjoying the patio, the pool, Taking a shower, Getting a drink, Looking for snacks, Preparing a meal, Heating up some food, Making coffee and lattes, washing and grooming at the bathroom sink, stargazing, career work at the computer, kitchen and workshop, and "Having private adult romantic time" for a couple that cannot conceive. Age-appropriate, as in VF2: online shopping from 13, social media, teen games and teen homework from 14, child pool games and homework for younger villagers, bath toys for children and spa days from 14, jewelry for girls and women from 14. At the computer, browsing the web and playing video games are chosen 50:50, as in VF2, both when a villager is dropped on the computer and when one picks an activity by itself. Apart from that, the behaviors, their chances and career progression are not changed.'),
}


def settings_from(rows):
    return vp.manifest_settings({"settings": rows})


def ns(**kw):
    base = dict(game_dir=None, output_dir=None, output_parent_dir=None, manifest=None, backup_dir=None, log=None,
                dry_run=False, enable=None, disable=None, enable_all=False, disable_all=False, exe_name=None,
                dll=None, exe=None, progress_callback=lambda message: None)
    base.update(kw)
    return argparse.Namespace(**{k: (str(v) if isinstance(v, Path) else v) for k, v in base.items()})


# ---------------------------------------------------------------- manifest

def test_shipped_manifest_offers_every_setting_all_on():
    settings = vp.manifest_settings(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert list(settings) == list(SPEC)
    for setting_id, (label, description) in SPEC.items():
        s = settings[setting_id]
        assert (s.label, s.description, s.default) == (label, description, True)
    assert settings["FixVanillaGameBugs"].category == "main"


@pytest.mark.parametrize("rows, message", [
    ([{"id": "A"}, {"id": "a"}], "Duplicate"),
    ([{"id": "A", "requires": ["B"]}], "unknown setting"),
    ([{"id": "A", "requires": ["B"]}, {"id": "B", "requires": ["A"]}], "depends on itself"),
    ([{"id": "A", "requires": ["A"]}], "cannot require itself"),
    ([{"id": "A", "default": "yes"}], "true or false"),
    ([{"id": "A=1"}], "unsupported"),
    ([{"id": "A", "files": [{"source": "x.png", "target": "Images/x.png"}]}], "must be inside"),
    ([{"id": "A", "files": [{"source": "x", "target": "Virtual Families 1 Patcher Files/settings.ini"}]}], "belongs to the patcher"),
    ([{"id": "A", "files": [{"source": "x", "target": "Virtual Families 1 Patcher Files/../x"}]}], "'..'"),
    ([{"id": "A", "files": [{"source": "x", "target": "Virtual Families 1 Patcher Files/x"}]},
      {"id": "B", "files": [{"source": "y", "target": "virtual families 1 patcher files/X"}]}], "both"),
])
def test_manifest_mistakes_are_refused(rows, message):
    with pytest.raises(vp.PatchError, match=message):
        settings_from(rows)


def test_dependencies_are_transitive_and_stated_in_bold():
    settings = settings_from([
        {"id": "Base", "label": "Base Patch"},
        {"id": "Mid", "label": "Middle", "requires": ["Base"]},
        {"id": "Top", "label": "Top", "requires": ["Mid"]},
    ])
    pre = vp.setting_prerequisites(settings)
    assert pre["Top"] == {"Mid", "Base"} and pre["Base"] == frozenset()
    assert vp.requires_note(pre["Top"], settings) == " **Requires: Base Patch, Middle.**"
    report = vp.effective_settings_report(settings, {"Top", "Mid"})
    assert report["enabled"] == set()
    assert report["inactive"]["Top"] == "selected but inactive: requires Base Patch"


def test_selection_order_defaults_then_all_then_each():
    settings = settings_from([{"id": "A", "default": True}, {"id": "B"}, {"id": "C"}])
    assert vp.resolve_enabled_settings(settings, ns()) == {"A"}
    assert vp.resolve_enabled_settings(settings, ns(disable_all=True, enable=["B,C"])) == {"B", "C"}
    assert vp.resolve_enabled_settings(settings, ns(enable_all=True, disable=["A"])) == {"B", "C"}
    with pytest.raises(vp.PatchError, match="Unknown"):
        vp.resolve_enabled_settings(settings, ns(enable=["Nope"]))
    with pytest.raises(vp.PatchError, match="both"):
        vp.resolve_enabled_settings(settings, ns(enable=["B"], disable=["B"]))


# ------------------------------------------------------------- settings.ini

def test_new_settings_ini_has_one_line_per_setting():
    data = vp.render_settings_ini(None, {"A": 1, "B": 0})
    assert data.startswith(b"[Patches]\r\n;")
    assert vp.read_ini_section(data, "Patches") == {"A": "1", "B": "0"}


def test_settings_ini_keeps_everything_else():
    old = (b"; top comment\r\n[Cheats]\r\nInterestRate=7.5\r\n\r\n[patches]\r\nfleamarket=1\r\n"
           b"FutureThing=1\r\n; note\r\nFleaMarket=0\r\n\r\n[Other]\r\nx=\xe9\r\n")
    new = vp.render_settings_ini(old, {"FleaMarket": 0, "RollTheDice": 1})
    assert vp.read_ini_section(new, "Cheats") == {"InterestRate": "7.5"}
    assert vp.read_ini_section(new, "Other") == {"x": "\xe9"}
    assert vp.read_ini_section(new, "Patches") == {"FleaMarket": "0", "FutureThing": "1", "RollTheDice": "1"}
    assert b"; top comment" in new and b"; note" in new and b"x=\xe9" in new  # ANSI bytes kept
    assert new.count(b"FleaMarket") == 1  # the duplicate the DLL would never read is gone
    assert vp.render_settings_ini(new, {"FleaMarket": 0, "RollTheDice": 1}) == new  # stable


def test_settings_ini_unicode_file_stays_unicode():
    old = "﻿[Cheats]\r\nInterestRate=3\r\n".encode("utf-16-le")
    new = vp.render_settings_ini(old, {"A": 1})
    assert new.startswith(b"\xff\xfe")
    assert vp.read_ini_section(new, "Cheats") == {"InterestRate": "3"}
    assert vp.read_ini_section(new, "Patches") == {"A": "1"}


# ---------------------------------------------------------------- naming

@pytest.mark.parametrize("name", ["Virtual Families Patched.exe", "PATCH.exe", "vf1-patcher.exe",
                                  "Virtual Families.exe", "virtual families.EXE", "Modded", "a/b.exe", "x?.exe"])
def test_bad_modded_exe_names_are_refused(name):
    with pytest.raises(vp.PatchError):
        vp.validate_exe_name(name)


def test_default_exe_name():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert vp.manifest_output_exe_name(manifest) == "Virtual Families - Modded.exe"
    manifest["output"]["default_exe_name"] = "Virtual Families Patch.exe"
    with pytest.raises(vp.PatchError, match="patch"):
        vp.manifest_output_exe_name(manifest)


def test_default_output_parent_avoids_program_files(monkeypatch, tmp_path):
    pf = tmp_path / "Program Files (x86)"
    monkeypatch.setenv("ProgramFiles(x86)", str(pf))
    assert vp.default_output_parent(pf / "Virtual Families") == Path.home() / "Games"
    assert vp.default_output_parent(tmp_path / "Games" / "Virtual Families") == (tmp_path / "Games").resolve()


def test_transparency_log_is_current_and_names_every_setting():
    text = vp.transparency_log_text(json.loads(MANIFEST.read_text(encoding="utf-8")))
    committed = (ROOT / "release" / "Transparency Log.txt").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == text, "run: python tools/package_release.py --transparency-log"
    for setting_id, (label, description) in SPEC.items():
        assert f"{setting_id} [on]" in text and label in text and description in text


def test_transparency_log_lists_setting_files(tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["settings"].append({"id": "Extra", "label": "Extra Art", "requires": ["CheatUpgrades"],
                                 "files": [{"source": "art/x.png", "target": "Virtual Families 1 Patcher Files/x.png"}]})
    text = vp.transparency_log_text(manifest)
    assert "Virtual Families 1 Patcher Files\\x.png: only while Extra Art is on" in text
    assert "**Requires: Cheat Upgrades.**" in text


# ------------------------------------------------------ against the game

def apply(workdir, **kw):
    args = ns(manifest=workdir / "patcher" / "manifest.json", **kw)
    assert vp.apply_manifest(args) == 0
    return args.last_apply_summary


def ini(output):
    return (output / vp.SETTINGS_REL).read_bytes()


def test_dry_run_writes_nothing_but_its_log(workdir, vanilla_unchanged):
    out = workdir / "out"
    summary = apply(workdir, game_dir=vanilla_unchanged, output_dir=out, dry_run=True)
    assert not out.exists()
    assert summary["dry_run"] and Path(summary["log_path"]) == workdir / "patcher" / "patch_dry_run_log.json"


def test_build_writes_exactly_the_transparency_log_files(workdir, vanilla_unchanged):
    out = workdir / "Virtual Families - Modded"
    summary = apply(workdir, game_dir=vanilla_unchanged, output_dir=out, disable=["RollTheDice"])
    vanilla_files = set(vp.vanilla_rel_files(vanilla_unchanged))
    written = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    backups = {f for f in written if f.startswith(vp.DEFAULT_BACKUP_ROOT + "/")}
    extra = written - vanilla_files - backups
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = [row for setting in manifest["settings"] for row in setting.get("files", [])]
    replaced = {row["target"] for row in rows if row.get("replaces")}
    added = {row["target"] for row in rows if not row.get("replaces")}
    originals = {vp.original_store_rel(t) for t in replaced}
    assert extra == {"Virtual Families - Modded.exe", vp.DLL_REL, vp.SETTINGS_REL} | added | originals
    assert not (out / vp.VANILLA_EXE).exists()
    for rel in vanilla_files - replaced:
        assert (out / rel).read_bytes() == (vanilla_unchanged / rel).read_bytes()
    for rel in replaced:  # the game file is the setting's art; the original is kept beside the patcher's files
        assert (out / rel).read_bytes().startswith(b"stand-in for ")
        assert (out / vp.original_store_rel(rel)).read_bytes() == (vanilla_unchanged / rel).read_bytes()
    assert (out / "Virtual Families - Modded.exe").read_bytes() == vp.patch_executable(
        (vanilla_unchanged / vp.VANILLA_EXE).read_bytes())
    assert vp.read_ini_section(ini(out), "Patches") == {
        "FixVanillaGameBugs": "1", "OlderVillagerMortalityCurve": "1", "PrivateRomanticTime": "1", "AllowOlderPregnancies": "1", "ClampMoneyAndFood": "1", "SpecialUpgrades": "1",
        "CheatUpgrades": "1", "FleaMarket": "1", "RollTheDice": "0", "CustomMapImages": "1", "VF2Songs": "1", "GlowingCollectables": "1", "BehaviorLabelVariants": "1"}
    text = vp.transparency_log_text(json.loads(MANIFEST.read_text(encoding="utf-8")))
    for rel in extra - originals:
        assert rel.replace("/", "\\") in text
    for setting in manifest["settings"]:
        for row in setting.get("files", []):
            if row.get("replaces"):
                assert row["target"].replace("/", "\\") + ": replaced only while " + setting["label"] + " is on" in text
    for name in {Path(b).name for b in backups if "/files/" not in b}:
        assert name in text
    assert summary["modded_save_dir"].endswith("LDW\\Virtual Families - Modded")


def test_reconfigure_only_rewrites_settings_and_restore_puts_it_back(workdir, vanilla_unchanged):
    out = workdir / "out"
    apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    exe = out / "Virtual Families - Modded.exe"
    exe_before = exe.read_bytes()
    with open(out / vp.SETTINGS_REL, "ab") as f:  # what the DLL writes in play
        f.write(b"[Cheats]\r\nInterestRate=9\r\n")
    before = ini(out)
    summary = apply(workdir, output_dir=out, disable=["FleaMarket", "CheatUpgrades"])
    assert summary["mode"] == "existing_modded_output"
    assert [row["file_path"] for row in summary["written_files"]] == [vp.SETTINGS_REL]
    assert vp.DLL_REL in summary["unchanged_files"]
    assert exe.read_bytes() == exe_before
    assert vp.read_ini_section(ini(out), "Patches") == {
        "FixVanillaGameBugs": "1", "OlderVillagerMortalityCurve": "1", "PrivateRomanticTime": "1", "AllowOlderPregnancies": "1", "ClampMoneyAndFood": "1", "SpecialUpgrades": "1",
        "CheatUpgrades": "0", "FleaMarket": "0", "RollTheDice": "1", "CustomMapImages": "1", "VF2Songs": "1", "GlowingCollectables": "1", "BehaviorLabelVariants": "1"}
    assert vp.read_ini_section(ini(out), "Cheats") == {"InterestRate": "9"}
    vp.restore_backup(ns(backup_dir=summary["backup_dir"], force_game_dir=False))
    assert ini(out) == before


def test_rebuild_keeps_remembered_cheats_and_restore_undoes_a_first_build(workdir, vanilla_unchanged):
    out = workdir / "out"
    first = apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    with open(out / vp.SETTINGS_REL, "ab") as f:
        f.write(b"[Cheats]\r\nInterestRate=4\r\n")
    (out / "Sounds" / "stray.txt").write_text("left over")
    second = apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    assert vp.read_ini_section(ini(out), "Cheats") == {"InterestRate": "4"}
    assert not (out / "Sounds" / "stray.txt").exists()
    # Restoring the second run's backup brings the stray file back.
    vp.restore_backup(ns(backup_dir=second["backup_dir"]))
    assert (out / "Sounds" / "stray.txt").read_text() == "left over"
    # Restoring the first run's backup removes everything that run created.
    vp.restore_backup(ns(backup_dir=first["backup_dir"]))
    left = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert {f for f in left if not f.startswith(vp.DEFAULT_BACKUP_ROOT + "/")} == {"Sounds/stray.txt"}


def test_setting_files_follow_their_setting(workdir, vanilla_unchanged):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["settings"].append({"id": "Extra", "label": "Extra", "default": True, "requires": ["FleaMarket"],
                                 "files": [{"source": "art/x.png", "target": "Virtual Families 1 Patcher Files/art/x.png"}]})
    write_manifest(workdir / "patcher" / "manifest.json", settings=manifest["settings"])
    (workdir / "patcher" / "payload" / "art").mkdir()
    (workdir / "patcher" / "payload" / "art" / "x.png").write_bytes(b"png")
    out = workdir / "out"
    apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    target = out / "Virtual Families 1 Patcher Files" / "art" / "x.png"
    assert target.read_bytes() == b"png"
    off = apply(workdir, output_dir=out, disable=["FleaMarket"])  # Extra's prerequisite
    assert not target.exists()
    assert off["removed_files"] == ["Virtual Families 1 Patcher Files/art/x.png"]
    assert vp.read_ini_section(ini(out), "Patches")["Extra"] == "0"
    assert "requires Flea Market" in off["settings"]["selected_but_inactive"]["Extra"]
    vp.restore_backup(ns(backup_dir=off["backup_dir"]))
    assert target.read_bytes() == b"png"


def test_exe_argument_builds_or_reconfigures(workdir, vanilla_unchanged):
    summary = apply(workdir, exe=vanilla_unchanged / vp.VANILLA_EXE, output_parent_dir=workdir)
    out = workdir / "Virtual Families - Modded"
    assert Path(summary["output_dir"]) == out.resolve() and summary["mode"] == "vanilla_to_modded_output"
    again = apply(workdir, exe=out / "Virtual Families - Modded.exe", disable=["RollTheDice"])
    assert again["mode"] == "existing_modded_output"


def test_refusals(workdir, vanilla_unchanged):
    out = workdir / "out"
    for kw, message in [
        (dict(game_dir=vanilla_unchanged, output_dir=vanilla_unchanged), "separate folder"),
        (dict(game_dir=vanilla_unchanged, output_dir=vanilla_unchanged / "Modded"), "not inside"),
        (dict(output_dir=workdir / "patcher"), "not recognized"),
        (dict(game_dir=vanilla_unchanged, output_dir=out, exe_name="Patched VF.exe"), "patch"),
    ]:
        with pytest.raises(vp.PatchError, match=message):
            apply(workdir, **kw)
    (workdir / "mine").mkdir()
    (workdir / "mine" / "notes.txt").write_text("my files")
    with pytest.raises(vp.PatchError, match="not recognized"):
        apply(workdir, game_dir=vanilla_unchanged, output_dir=workdir / "mine")
    assert (workdir / "mine" / "notes.txt").read_text() == "my files"
    apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    with pytest.raises(vp.PatchError, match="already-patched"):
        apply(workdir, game_dir=out, output_dir=workdir / "out2")
    # A modded executable from another patcher version needs the vanilla folder.
    exe = out / "Virtual Families - Modded.exe"
    data = bytearray(exe.read_bytes())
    raw = {s[0]: s for s in vp.PE(bytes(data)).sections()}[".vf1fun"][3]
    data[raw + 10] ^= 0xFF
    exe.write_bytes(bytes(data))
    with pytest.raises(vp.PatchError, match="different version"):
        apply(workdir, output_dir=out)


def test_pinned_payload_must_match(workdir, vanilla_unchanged):
    manifest_path = workdir / "patcher" / "manifest.json"
    write_manifest(manifest_path, payload={vp.DLL_NAME: {"sha256": "0" * 64, "size": 1}})
    with pytest.raises(vp.PatchError, match="does not match"):
        apply(workdir, game_dir=vanilla_unchanged, output_dir=workdir / "out", dry_run=True)
    assert json.loads((workdir / "patcher" / "patch_error_log.json").read_text())["status"] == "failure"


def test_restore_guards(workdir, vanilla_unchanged):
    out = workdir / "out"
    summary = apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    with pytest.raises(vp.PatchError, match="different folder"):
        vp.restore_backup(ns(backup_dir=summary["backup_dir"], game_dir=workdir, force_game_dir=False))
    with pytest.raises(vp.PatchError, match="vanilla game folder"):
        vp.restore_backup(ns(backup_dir=summary["backup_dir"], game_dir=vanilla_unchanged, force_game_dir=True))


def test_cli_reports_errors_with_exit_code_2(workdir, capsys):
    assert vp.main(["apply", "--manifest", str(workdir / "patcher" / "manifest.json")]) == 2
    assert "ERROR:" in capsys.readouterr().err
    assert vp.main(["settings", "--manifest", str(MANIFEST)]) == 0
    assert "RollTheDice [default on] - Roll the Dice" in capsys.readouterr().out


def test_replaced_game_files_are_put_back_when_their_setting_is_off(workdir, vanilla_unchanged):
    out = workdir / "out"
    apply(workdir, game_dir=vanilla_unchanged, output_dir=out)
    rows = [row for setting in json.loads(MANIFEST.read_text(encoding="utf-8"))["settings"]
            if setting["id"] == "CustomMapImages" for row in setting["files"]]
    targets = [row["target"] for row in rows]
    assert targets and all((out / t).read_bytes().startswith(b"stand-in for ") for t in targets)
    # Switching it off (no vanilla folder needed) puts every original back and drops the saved copies.
    off = apply(workdir, output_dir=out, disable=["CustomMapImages"])
    for t in targets:
        assert (out / t).read_bytes() == (vanilla_unchanged / t).read_bytes()
        assert not (out / vp.original_store_rel(t)).exists()
    assert vp.read_ini_section(ini(out), "Patches")["CustomMapImages"] == "0"
    # Switching it on again saves the originals first, then writes the art.
    apply(workdir, output_dir=out)
    for t in targets:
        assert (out / t).read_bytes().startswith(b"stand-in for ")
        assert (out / vp.original_store_rel(t)).read_bytes() == (vanilla_unchanged / t).read_bytes()
    # A restore of the off-run brings the art back exactly as it was.
    vp.restore_backup(ns(backup_dir=off["backup_dir"], force_game_dir=False))
    for t in targets:
        assert (out / t).read_bytes().startswith(b"stand-in for ")


def test_a_replaced_file_must_be_under_images():
    with pytest.raises(vp.PatchError, match="must be under"):
        settings_from([{"id": "A", "files": [{"source": "x.png", "target": "Sounds/x.png", "replaces": True}]}])
