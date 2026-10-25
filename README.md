# Virtual Families 1 Fun Patcher

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
  - Adopt Outside Boy and Adopt Outside Girl (age 2-13, optional name; the
    abandoned-child adoption of the game's own Little Visitor event: an
    outside child with no parents in the house joins the Family Tree);
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

Six settings change the base game on their own (plus the optional ones below):
- **Older Villager Mortality Curve:** VF2's calibrated old-age death curve, with
  no hard maximum age. Because parents can live on, the Family Tree's Next
  Generation button is also offered once the oldest parent at home is 60 and a
  child survives.
- **Private Adult Romantic Time:** a married opposite-sex couple at six children
  can still have private romantic time (the game refused with "They have enough
  kids already!"), with the stock cooldown, as in the VF2 patcher.
- **Clamp Max Money and Food:** coins stay at or under 4,000,000,000 and food at or under
  2,147,483,647 (the VF2 maximums); the original game has no limit and food wraps negative.
- **Behavior Label Variants** (optional): the caption under a villager varies, using the VF2 patcher's own captions,
  for TV, reading, the web, video games, board games, homework, the sandbox, the flower boxes, naps (with the
  sit-down captions), the pool, career work and private adult romantic time. At the computer, browsing the web
  and playing video games are chosen 50:50, as in VF2 (dropped on the computer or choosing by itself), with
  the computer used as often as in the original game and nothing in the save changed; apart from that,
  behaviors, chances and career progression are unchanged.
- **Allow Older Pregnancies:** mothers over 50 can still conceive (10% at 50, tapering
  to a 0.1% floor from 69), as in the VF2 patcher.
- **Fix Vanilla Game Bugs:** a brand-new family is kept if the game is closed
  without quitting, and Power Failure's "keep the food" result text matches
  what happens.
- **Up to 28 Children** (in the patcher's own **Experimental** section, red heading, after Optional
  Patches, with the warning "Experimental: not yet tested in a running game. Back up your saves before using it."; off by default, and Enable All and `--enable-all` leave it off,
  so it is only ever ticked deliberately): one generation may have up to 28 children instead of
  6. Only the first 6 appear in the Family Tree, as before; every child, the
  7th to the 28th included, can be chosen to inherit the house in Next
  Generation. Twins and triplets never take a family past 28 (27 children: a
  twin or triplet pregnancy has one baby; 26: a triplet pregnancy has two), and
  the normal chances are unchanged while there is room. Children 7 to 28 are
  remembered in a small file beside each save (`Virtual Families 1 Patcher
  Data\Children`); the save file itself is not changed. Virtual Families 1 natively keeps up to 6 children per generation in its Family Tree, and a household holds at most 30 villagers (2 parents and 28 children). This patch keeps children 7 to 28 in a separate file beside the save, so they never overwrite Family Tree entries; storing more than 6 children in the Family Tree itself would overwrite its entries and glitch the game. Experimental: not yet tested in a running game. Back up your saves before using it.
  It is its own DLL, `vf1kids.dll`, installed only while the setting is on.
  **Not live tested yet** -- see `docs/UP_TO_28_CHILDREN.md`.

- **Family Logs** (also in the **Experimental** section, off by default): the Virtual Villagers Fun
  Patcher's logs for your family, written as things happen: a Family History (every event, one line
  each), Births and Conceptions, Deaths (with the game's own cause of death), Events (the patcher's own:
  Roll the Dice, Divorce Spouse, Evict Family, Adopt New Person, Spawn Child, Adopt Outside Child, Boarding
  School), and at each save the Family Population and Family Statistics. One folder per save slot,
  `Virtual Families 1 Patcher\Save N\Logs` (data files in `Save N\Data`). An existing family's past
  generations come from its Family Tree, marked "backfilled, no date", once; a new family or Start Over
  clears that slot's folder (Backups kept). Its own DLL, `vf1logs.dll`. **Not live tested yet** -- see
  `docs/FAMILY_LOGS.md`.

Players: see [release/How to Use.txt](release/How to Use.txt).

## The patcher window: Patches and Tools

The window has two tabs, as in the Virtual Villagers Fun Patcher:
- **Patches:** the patch selection (Patch Input, Patch Settings, Dry Run, Enable/Disable
  Patches, Restore Backup) exactly as before, with Check for updates in the header.
- **Tools:** things that are not patches. For now:
  - **Back Up Saves:** copies the modded game's save folder
    (`Documents\LDW\Virtual Families - Modded`: the `Virtual Families<N>.ldw` slot saves, plus the patcher's own
    `Virtual Families 1 Patcher Data` folder with each save's Slot files and the Children
    files) into a new `Backups\Backup <date and time>` folder inside it. The save folders are found
    automatically (Documents is read from Windows, so a OneDrive-redirected Documents works). A running game is
    paused for the copy and resumed; every copy is checked against the original (size and SHA-256); an existing
    backup is never replaced, and a copy that fails is kept as `... INCOMPLETE` and never offered for restore.
  - **Restore Saves:** lists the backups (newest first) and puts one back, the whole folder or one save slot.
    The game must be closed. It shows exactly which files will be replaced, added and removed, **asks you to
    confirm**, and first backs up your current saves as `Backup <date> (before restore)`; if the restore fails
    part-way every file is put back. **Delete Backup...** removes a backup you no longer want (it asks first).
  - **Check Saves & Logs:** for one save slot, compares the Family Logs and their data files with the save (and
    the game's older copies of it, `Virtual Families<N+20>.ldw` / `<N+40>.ldw`, when they hold the same family)
    and lists each contradiction in plain words as OK / WRONG / ASK / NOTE / UNCHECKED: family members missing
    from the logs, Death records of members still alive, records logged twice, members gone with no record of
    how (Unaccounted), parents that disagree, Family Statistics / Population pages and counters that do not add
    up. It only reads.
  - **Repair Saves & Logs:** with the game closed, shows each repair with its evidence (confirmed wrong: ticked)
    and each question with its choices ("Don't know" always changes nothing), then, once confirmed, backs the
    save folder up (`Backup <date> (before repair)`, offered by Restore Saves), copies each file into
    `Save N\Copies Made Before Repairs` before changing it, and writes one `Repair <n>` record (every change,
    the removed lines, every answer) in `Save N\Logs\Repairs Made`. Answers are kept and never asked again;
    **Answered Questions...** changes or clears one. **The save itself is never changed**: no Virtual Villagers
    patcher save repair has a counterpart here on a VERIFIED save field, so every repair is log-only.
  - Every button, patch and setting has a small **"?"** beside it that opens a brief How to Use guide, written
    in `patcher/how_to_use.json`; `tests/test_how_to_use.py` refuses a patch or button without one. The
    Tools tab's *Getting started* link opens the overview.

The save tools live in `patcher/vf1_save_backup.py` (no Tk; tested with temporary copies only, see
`tests/test_save_backup.py` and `tests/test_tools_tab.py`) and the guides in `patcher/vf1_how_to_use.py`.
Check / Repair Saves & Logs live in `patcher/vf1_log_tools.py` (no Tk; `tests/test_log_tools.py` and
`tests/test_log_tools_window.py`, including logs written by the real `vf1logs.dll` under emulation for copies of
real saves). `python patcher/vf1_log_tools.py <save folder> <slot>` prints the check's report.

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
Restore Backup; the Patches tab, plus a Tools tab as in the Virtual Villagers patcher), the same `apply` / `settings` / `restore` commands, backups
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

- **DLLs:** `native\build.bat` builds `build\vf1fun.dll`,
  `native\build_kids.bat` builds `build\vf1kids.dll` (Up to 28 Children) and
  `native\build_logs.bat` builds `build\vf1logs.dll` (Family Logs).
  They need Visual Studio's 32-bit C++ tools.
- **Loader stub:** `python tools/build_stub.py` rebuilds `patcher/stub.json`
  after a change. It needs `keystone-engine`.
- **Release zip:** `python tools/package_release.py VERSION` writes
  `outputs/Virtual-Families-1-Fun-Patcher-VERSION.zip`, laid out like a VF2 release (Launch_GUI.bat,
  Apply_VERSION_Patcher.bat, How to Use.txt, README, Transparency Log.txt,
  manifest.json with each payload file's SHA-256 and size, the scripts,
  payload/vf1fun.dll and payload/vf1kids.dll).
- **Tests:** set `VF1_VANILLA_DIR` to a copy of your own vanilla Virtual
  Families folder (or `VF1_VANILLA_EXE` to its executable, for the
  executable-only tests), then run `pytest tests`. The tests only read that
  folder. Install the test tools with `pip install -r requirements-dev.txt`.

### Running the tests in parallel

`python scripts/run_tests_parallel.py` runs the whole suite at once: one
pytest process per test file, with the two slow files
(`test_up_to_28_children.py`, `test_engine.py`) cut into several jobs. Every
job gets its own short temp folder, and every DLL a test builds goes there
(`native\build_kids.bat` honours `VF1_BUILD_DIR`), so no two jobs write the
same file. A job that fails is run again on its own, and only what still fails
alone counts; the summary is printed and written to
`%TEMP%\vf1-parallel-tests\summary.txt` (change it with `--out`, the number of
processes with `--workers`). It exits 1 if anything still fails alone. On a
16-worker run the full suite takes about 1.5 minutes instead of about 6.

**Release-only tests.** A test that takes 15 seconds or more is listed in
`RELEASE_ONLY` in `tests/conftest.py`: a plain `pytest` run skips it and says
so; `pytest --release` (or `VF1_RELEASE=1`) runs it. The parallel runner
passes `--release` unless you give it `--quick`, and the run before a release
must be a full one (`python scripts/run_tests_parallel.py`, no `--quick`).
`tests/test_release_only.py` checks that every listed entry is a real test.

**CI.** `.github/workflows/tests.yml` runs `pytest tests` on Windows with
Python 3.12 for every pull request and every push to `main`, and puts a per-file
table on the run's Summary tab (the JUnit report is kept as an artifact). CI
has no game files and no Visual Studio 18 toolchain, so every test that needs
them skips with its reason: CI checks the manifest, engine, GUI, release
bundle and source-level tests, and the patched-executable, emulated-DLL and
native-build tests are checked only by a local run with the vanilla copy.

## Related projects

- [Virtual Families 2 Restoration/Addition Patcher](https://github.com/Lorsieab2/Virtual-Families-2-Restoration-Addition-Patcher)
- Virtual Villagers Fun Patcher
