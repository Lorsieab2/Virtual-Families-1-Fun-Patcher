# Virtual Families 1 Patcher

A patcher for **Virtual Families** (Last Day of Work, 2014; PC version 1.01.00),
adding features from Virtual Families 2 and new cheats.

## What it adds

The store gets a new **Upgrades** button, next to Done. It opens ordinary
Windows dialogs, the way the Virtual Villagers Fun Patcher works. The pages
(Cheat Upgrades, Flea Market, Roll the Dice and Special Upgrades are separate
patch settings you can switch off):

- **Cheat Upgrades:**
  - money: No Money, +100, +10,000, Max, or set an exact amount;
  - food: No Food, +100, +10,000, Max, or set an exact amount;
  - change the bank's interest rate (1% to 11%), which is remembered between sessions.
  - Cheat money doesn't count toward the money achievements. The Clamp Max Money and Food setting keeps both at the VF2 maximums.
- **Villager Cheats:** for one villager or everyone (each button asks you to confirm):
  - max health, cure illnesses, max happiness, max energy, fill up (Fed);
  - Instant job promotion, and Career Change (adults with a career);
  - Boarding School: a child leaves the house, as in the game's own "going to
    college" departure;
  - Systematic Desensitization (removes a dislike), Higher Learning Classes (a
    new like), Psychotherapy (overcomes depression), Add Running Like;
  - Set Age to 18 (the selected villager only);
  - Change Appearance: any of the game's 50 heads (face and hairstyle) and 50
    bodies (clothes), or a random look. VF1 has no separate clothing or hair
    field, so these two rows are the whole look.
- **Store, Achievement and Collection Cheats:** store price multipliers,
  complete or reset achievements and collections.
- **House and Yard:** fill the house with trash or the yard with weeds, Clean
  House, Clean Garden, trigger or fix all house malfunctions.
- **Time Controls:** pause, resume, 2x / 5x / 10x speed, time warp (+3
  years).
- **Special Upgrades:** VF2-style purchases (Brokerage Account, Food Club,
  Health Plan, Lucky Rock) plus a Maid and a Gardener who keep the house and
  yard clean, and the Anti-spam Software (no computer needed). Each asks for
  confirmation and shows a "Purchased" message; buying one again removes it
  (no refund), as in VF2. Flea Market purchases and Roll the Dice do the same.
- **Family:**
  - Enable Same-Sex Marriage, and Allow Reroll of Marriage Candidates;
  - Force Marriage Email, and Divorce Spouse;
  - next pregnancy one-shots: force success, boys or girls, singleton, twins
    or triplets;
  - Spawn Male Child and Spawn Female Child (age 2-13, optional name; a child of
    the current couple, with their looks);
  - Adopt New Person (only after "your family has been lost"), which keeps
    your money and the Family Tree;
  - Evict Family: resets the Family Tree and starts a new family, keeping the
    money and the house.
- **Patcher Achievements:** the Virtual Families 2 patcher's achievements that
  fit this game, with the same names (Lucky 70's, Great 80's, Mighty 90's,
  Centenarian, Oldest Person in History, Return of the Rainbow, Spiky!,
  Blue's Clues, A Decade in Blue,
  Achiever Extraordinaire; the maximum coins and food ones use the clamp's limits), kept per village on their own page. The game's
  Trophies screen is unchanged.
- **Flea Market:** every tray item the store sells, to buy or get for free.
- **Roll the Dice:** costs $500, and an island event happens right away,
  through the game's own event system.
- **Counters** on the menu: Generation and Oldest Villager.

Five settings change the base game on their own (plus the optional ones below):
- **Older Villager Mortality Curve:** VF2's calibrated old-age death curve, with
  no hard maximum age. Because parents can live on, the Family Tree's Next
  Generation button is also offered once the oldest parent at home is 60 and a
  child survives.
- **Private Adult Romantic Time:** a married opposite-sex couple at six children
  can still have private romantic time (the game refused with "They have enough
  kids already!"), with the stock cooldown, as in the VF2 patcher.
- **Clamp Max Money and Food:** coins stay at or under 4,000,000,000 and food at or under
  2,147,483,647 (the VF2 maximums); the original game has no limit and food wraps negative.
- **Behavior Label Variants** (optional): the caption under a villager varies for Watching TV, Reading,
  Browsing the web, Playing video games, Taking a nap and the pool (laps, diving, cannonballs), as in VF2.
  Captions only: behaviors, chances and career progression are unchanged.
- **Allow Older Pregnancies:** mothers over 50 can still conceive (10% at 50, tapering
  to a 0.1% floor from 69), as in the VF2 patcher.
- **Fix Vanilla Game Bugs:** a brand-new family is kept if the game is closed
  without quitting, and Power Failure's "keep the food" result text matches
  what happens.

Players: see [release/How to Use.txt](release/How to Use.txt).

## Planned

- **Cut content:** restored where the game ships unused text or art.

Data the game itself does not track (the purchases, the Family page's choices)
is kept per save slot in the patcher's own files under
`Documents\LDW\<exe name>\Virtual Families 1 Patcher Data`, never inside the
game's records.

## How it works

The patcher writes a patched **copy** of the game into a new folder. The
original game folder is never changed. The patched executable gets one small
loader:
- it lives in its own read-and-execute section;
- its state lives in a separate read-write section;
- it is entered from two places: game start-up and the store screen.

The loader loads `Virtual Families 1 Patcher Files\vf1fun.dll` by full path.
If that DLL is missing, the game runs exactly as normal.

The patcher program is a port of the Virtual Families 2 patcher's: the same
window (Patch Input, Patch Settings, Run Log, Dry Run, Enable/Disable Patches,
Restore Backup), the same `apply` / `settings` / `restore` commands, backups
under `.vf1_patch_backups` in the modded folder, and JSON patch logs.
- **Settings** come from [patcher/manifest.json](patcher/manifest.json): one
  row per patch with its id, label, description, default, category and,
  optionally, `requires` (stated in bold in the window) and `files` (installed
  in the Patcher Files folder only while the patch is on). Adding a patch to
  the window means adding a row there.
- **Switching patches** writes `Virtual Families 1 Patcher Files\settings.ini`,
  section `[Patches]`, `Key=1/0`, which the DLL reads. With only a modded
  folder selected, Enable/Disable Patches changes that file (and the setting
  files) in place; the executable is never patched again.
- **[release/Transparency Log.txt](release/Transparency Log.txt)** lists every
  file the patcher writes. It is generated from the manifest:
  `python tools/package_release.py --transparency-log`.

VF1 ships no symbols, but Virtual Families 2 is the same engine and a VF2 build
leaked its object files:
- **Checked names:** `tools/recover_function_names.py` transfers function names
  from those objects to VF1 through RTTI vtables, checked against VF1's own
  string table.
- **Hints only:** names that come from the call graph are kept separately as
  unverified hints.
- **Every address the patch uses** is recorded with its evidence in
  [data/vf1_verified.json](data/vf1_verified.json), and was checked in a live
  game where it matters.

This repository never contains game files. Tools take the paths of your own
copies as arguments.

## Building

- **DLL:** `native\build.bat` builds `build\vf1fun.dll`. It needs Visual
  Studio's 32-bit C++ tools.
- **Loader stub:** `python tools/build_stub.py` rebuilds `patcher/stub.json`
  after a change. It needs `keystone-engine`.
- **Release zip:** `python tools/package_release.py VERSION` writes
  `outputs/VF1-Patcher-VERSION.zip`, laid out like a VF2 release (Launch_GUI.bat,
  Apply_VERSION_Patcher.bat, How to Use.txt, README, Transparency Log.txt,
  manifest.json with the payload's SHA-256, the scripts, payload/vf1fun.dll).
- **Tests:** set `VF1_VANILLA_DIR` to a copy of your own vanilla Virtual
  Families folder (or `VF1_VANILLA_EXE` to its executable, for the
  executable-only tests), then run `pytest tests`. The tests only read that
  folder.

## Related projects

- [Virtual Families 2 Restoration/Addition Patcher](https://github.com/Lorsieab2/Virtual-Families-2-Restoration-Addition-Patcher)
- Virtual Villagers Fun Patcher
