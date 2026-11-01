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
  - max health, cure illnesses (every symptom and any infection, mild or serious), max happiness, max energy, fill up (Fed);
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
- **Roll the Dice:** costs $500, and a Popup Event happens right away,
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
- **R Refreshes the Store** (optional, on by default): pressing R (small or capital) in the store redraws its
  Flea Market, the six random items (the game's code calls them the specials), and the random Male Outfit and
  Female Outfit pictures, every time, with the game's own draw and odds. The original game has the same hidden
  key, a small r only, once more than 1 hour of real time has passed since the last draw. The half-price
  grocery, the other items and prices, and outfits already bought (each keeps its picture) are unchanged; R
  does nothing on any other screen or in the Upgrades menu's Flea Market page, which lists every tray item at once.
- **Behavior Label Variants** (optional): the caption under a villager varies, using the VF2 patcher's own captions,
  for TV, reading, the web, video games, board games, homework, the sandbox, the flower boxes, naps (with the
  sit-down captions), the pool, career work and private adult romantic time. At the computer, browsing the web
  and playing video games are chosen 50:50, as in VF2 (dropped on the computer or choosing by itself), with
  the computer used as often as in the original game and nothing in the save changed; apart from that,
  behaviors, chances and career progression are unchanged.
- **Allow Older Pregnancies:** mothers over 50 can still conceive (10% at 50, tapering
  to a 0.1% floor from 69), as in the VF2 patcher.
- **Fix Vanilla Game Bugs:** a brand-new family is kept if the game is closed
  without quitting, Power Failure's "keep the food" result text matches
  what happens, a family with a dog is offered the Pet Turtle (the original
  game checked for a dog instead of a turtle), and each outfit bought keeps its
  own picture in the tray and puts on that outfit (the original game showed and
  put on the last one bought for every outfit of a kind; the pictures are kept in
  `Virtual Families 1 Patcher Data\Outfits` beside each save, and the save is not changed).
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

- **Family History Log** (a Main Patch, on by default; Enable All ticks it like any other): one
  log, the Family History, of every family event, in the Virtual Villagers Fun Patcher's record layout and the
  game's own words: conceptions, births (twins and triplets, with both parents), deaths with cause and age,
  marriages and remarriages (the current spouse, the earlier one and why they left; any sexes), Divorce Spouse,
  who joins (Adopt Outside Child, The Little Visitor, Spawn Child, Adopt New Person) and who leaves home (college,
  Boarding School, The Talent Scout), Next Generation and its heir, a new family, Start Over, Evict Family, Roll the
  Dice, Rename Family, Copy Player Slot, and every Random Event as an Email Event or a Popup Event by the subject line or title the
  player sees. One file per save slot, `Virtual Families 1 Patcher\Save N\Logs\Family History\Family History
  <k>.txt`, rolling every 2000 records. An existing family gets what its Family Tree holds, marked "backfilled, no
  date", once; a new family or Start Over clears that slot's folder (Backups kept); Evict Family keeps it. Its own
  DLL, `vf1logs.dll`; every hook is emulated from a live caller. **Not live tested yet** -- see
  `docs/FAMILY_HISTORY.md`.

Players: see [release/How to Use.txt](release/How to Use.txt).

## The patcher window: Patches and Tools

The window has two tabs, as in the Virtual Villagers Fun Patcher:
- **Patches:** the patch selection (Patch Input, Patch Settings, Dry Run, Enable/Disable
  Patches, Restore Backup) exactly as before, with Check for updates in the header.
- **Tools:** things that are not patches. For now:
  - **Back Up Saves:** copies the modded game's save folder
    (`Documents\LDW\Virtual Families - Modded`: the `Virtual Families<N>.ldw` slot saves, plus the patcher's own
    `Virtual Families 1 Patcher Data` folder with each save's Slot files and the Children
    and Outfits files) into a new `Backups\Backup <date and time>` folder inside it. The save folders are found
    automatically (Documents is read from Windows, so a OneDrive-redirected Documents works). A running game is
    paused for the copy and resumed; every copy is checked against the original (size and SHA-256); an existing
    backup is never replaced, and a copy that fails is kept as `... INCOMPLETE` and never offered for restore.
    Game speed is set to Paused in the backup's family saves (the copies only; your own saves are unchanged), so
    a restored backup opens paused and never catches up on the time since it was made. Only a family at Normal is
    paused; a save at another speed, or one that cannot be read, is copied exactly as it is. A backup's Children
    file that matched its family save is re-matched to the paused copy (as Copy Player Slot does), so a restored
    backup keeps every extra child, including those who left home or died; one that did not match is copied as
    it is.
  - **Restore Saves:** lists the backups (newest first) and puts one back, the whole folder or one save slot.
    One save slot means the slot's saves, its `Slot <N>.ini`, Children and Outfits files and its
    `Virtual Families 1 Patcher\Save <N>` folder (Family History log, Family Tree files), so they all go back
    together.
    The game must be closed. It shows exactly which files will be replaced, added and removed, **asks you to
    confirm**, and first backs up your current saves as `Backup <date> (before restore)`; if the restore fails
    part-way every file is put back. **Delete Backup...** removes a backup you no longer want (it asks first).
  - **Rename Family...:** renames a family in a closed game's saves (the game must not be running). Pick a save
    slot and type the new name (printable ASCII, 1 to 19 characters; refused, never cut). It writes the verified
    family-name field of the slot save (and of its two older autosave copies when they hold the old name) and the
    slot-menu name in `Virtual Families0.ldw` (`docs/vf1-save-format.md`), first backing up everything as
    `Backup <date> (before rename)`; every file is checked after writing and put back if anything fails. A family
    with a Family History log gets one `Family Renamed` record in its newest file (old files keep their name).
    The slot's Children files that matched the renamed saves are re-matched to them (as Copy Player Slot does),
    so the game keeps every extra child (7 to 28) on the next load; one that did not match is left as it is.
    The module is `patcher/vf1_rename_family.py`, tested in `tests/test_rename_family.py`.
  - **Copy Player Slot...:** copies a family into another save slot under a new name, in a closed game's saves.
    Pick the family, any other slot and the new name (the Rename Family rule). A slot with no
    `Virtual Families<N>.ldw` is empty whatever `Virtual Families0.ldw` still says for it, and a slot whose save is
    there holds a family: the game does the same, rebuilding every slot's menu flag from whether its save loads at
    each start (`theGameState::Load` 0x4247C0). A slot that holds a family is replaced; the Yes / No question then
    starts "Save <N> holds the <old name> family. It will be replaced by a copy of ..." (No is the default: Return
    and Escape answer No). A slot is the game's `Virtual Families<N>.ldw` and its two older copies `<N+20>` / `<N+40>`, the
    patcher's `Slot <N>.ini`, `Children\Virtual Families<n>.ldw.dat` and `Outfits\Virtual Families<n>.ldw.dat`
    (and their `.unreadable-<k>.dat`) in `Virtual Families 1 Patcher Data`, and the `Virtual Families 1
    Patcher\Save <N>` folder (Family History log, Family Tree files): all are copied with the target's numbers.
    The new name goes into the copied save (and an older copy holding the old name) and into the target's
    slot-menu name in `Virtual Families0.ldw`, whose in-use flag for the target is set (traced in the stock exe:
    without it the menu shows the slot empty). Children files are re-matched to the copied save's bytes, the
    Family Tree files are renamed for the new slot, and the copied log gets one `Family Copied` record; outfit
    pictures need no change. The generated tree page and pictures and the slot's `Backups` are not copied. It
    backs up first as `Backup <date> (before copy)`, refuses while the game runs, then moves everything already
    in the target (a replaced family's save, `<N+20>` / `<N+40>`, sidecars and `Save <N>` folder, or what a family
    deleted in the game left) into `Backups\Replaced by copy <date> - Save <N> - <old name>\` keeping their paths
    (never deleted; Restore Saves never lists that folder), writes every file through a temporary file, the slot
    menu last, reads everything back, and moves everything back if anything fails. Module
    `patcher/vf1_copy_slot.py`, tests `tests/test_copy_slot.py`.
  - **Game Speed...:** shows each save's speed (Paused, Normal, an old Time Controls speed in words, or any other
    value raw) and sets a family to **Paused** or **Normal** in a closed game's save, writing what the game's own Pause / Unpause write (traced in
    the stock exe: Options 0x41E1CC / 0x41E21B, Space 0x440CB2, CGameTime::SetSpeed 0x422450, which stores 0 for
    999): the speed option gs+0x1B180 (10, or +999 when paused) and the saved CGameTime. Paused acts as if the game
    was paused just before it saved; Normal as if the paused family were unpaused now, so the clock carries on from
    where it stopped and each living villager's ageing stamp is set to now, exactly as the paused game's two-second
    update keeps it (0x489E6B): the paused time is never aged in. Any other speed is refused, as is an unpause that
    would have removed a dead body meanwhile. It backs up first as `Backup <date> (before speed change)`, writes
    only the slot save, reads it back, checks that no other byte changed and puts it back if anything fails. It
    writes no log. The slot's Children files that matched the save are re-matched to it (as Copy Player Slot
    does), so the game keeps every extra child on the next load; one that did not match is left as it is. The
    stock game sets no speed but 10 and the +999 pause. The patcher's own
    Time Controls speeds (Slow 20, Fast 5, 5x 2, 10x 1) are not offered either: vf1fun.dll saves every family at
    Normal (or Paused) and loads any save holding one of them at Normal (theGameState Save / Load wrappers, since
    v0.3.0), so no installed game can produce one in a save. A save the old v0.2.0 left at one is named in words
    and refused. Module `patcher/vf1_game_speed.py`, tests `tests/test_game_speed.py`.
  - **Game Mechanics...:** a read-only window, modelled on the Virtual Villagers Fun Patcher's, that shows how
    the stock game works underneath, grouped by topic with a link to each at the top: time and ageing (with the
    emulated time-away limits), needs and upkeep, health, sickness, old age and death, pregnancy and babies,
    careers (all 108 with their salaries), money and interest, leaving home, dating and marriage, the 71 e-mail
    and pop-up events, messes, collectibles, malfunctions, and a chance and timer index. Wherever the patcher
    changes what a line says, a "With the patcher" line follows it, naming the patch setting and whether it is on
    by default (verified with the patcher's own DLLs run beside the vanilla exe). Every time is real time
    at Normal with the Time Controls Slow and Fast beside it, and every line carries its evidence label:
    **VERIFIED-E** (the game's own routine emulated with the game's inputs, odds counted exactly),
    **VERIFIED-C** (the game's own code on a traced call path) or **UNCONFIRMED**. The facts are VF1's own, from
    `docs/game-mechanics/spec.md` and re-checks in the exe; the module's docstring records which of the owner's
    proposed lines held and which were left out. It opens no save, game file or install and writes nothing.
    Module `patcher/vf1_game_mechanics.py` (`python patcher/vf1_game_mechanics.py` prints the page), tests
    `tests/test_game_mechanics.py`.
  - **Picture Maker...:** the Fish and Plant Tycoon patcher's Picture Studio for Virtual Families 1. *From my
    save* lists a save's family members (at home, then those who left home) and the outfits in the store and the
    tool tray, and draws each as the game would now: their age, hair and face (head row), outfit (body row) and the
    babies they are expecting; a tray outfit uses the outfit fix's own picture when its sidecar matches the save
    (the patched look), else the stock game's last-bought one. *Make your own* builds anyone from gender, age, head
    0-49, body 0-49, any of the 56 house poses (32 walking frames in 4 directions, 15 actions, 9 sitting or lying),
    12 head turns, the game's 24 animations, shadow, ghost, babies on the way and anything carried, or the big
    portrait of the Adoption, Dating and family member screens (3 expressions), or an outfit as the store shows it.
    *Carrying* (both tabs) offers all 150 pictures a family member can be drawn holding (carrying.png's 78 and
    collectables_small.png's 72), named, grouped by kind and listed with the actions that carry them, read from
    the exe: every carry step (0x48CE70, 0x486A10) and where its number comes from (a constant, rand(n) + c, the
    grocery picker 0x47C1F0, the TV remote and shed door drops, the collectible and mess pick-ups). 135 are shown
    by the game; the 15 it never shows are offered too, marked so with the reason: seven unused carrying.png
    pictures (pizza, champagne, pot of stew, cutting board, soda, basket of odds and ends, paint can), the baby
    bundle (the game draws the babies on the way instead; drawn at the first baby's spot, marked "not checked
    against the game"), the blue sock (it vanishes the frame it appears), the second cobweb (never spawned) and
    the five blank cells. *Animation* sets the pose and direction from the game's table 0x4FBE90; five
    animations draw what is carried and the babies 10 or 20 pixels lower (0x48A105), the newspaper and magazines
    while lying down, and one hides the shadow (0x48B694). With the game
    folder's own pictures, the stock ones (Original Files) or the patcher's own (payload). PNGs are transparent,
    at game size, 2x, 4x or a custom size. Every rule comes from the game's own draw code (CVillagerManager
    0x48B4D0, CVillager 0x486B60, 0x496A10, Assets\animpts.dat and the loader 0x450F99, the blitter 0x404C30), and
    `tests/test_picture_maker.py` proves it with `tests/picture_emu.py`: the game's own drawing code runs in
    Unicorn on the vanilla exe and every planned draw (file, cell, place, scale, alpha) must equal the game's, at
    both 53- and 64-bit x87 precision; the game's blitter draws children, ghosts and outfits over three colours and
    the renderer's pixels must make the same screen; an adult's PNG must equal a Pillow composite of the cells
    at the emulated game's places; every carried number under every animation must draw as the game does, every
    carried picture's PNG must equal the Pillow composite, the animation start 0x485D50 must leave the pose and
    direction the renderer uses, and the carried numbers read from the exe must be the catalog's. No game art ships; the pictures are read from the game folder when drawn.
    Modules `patcher/vf1_picture_maker.py` (window), `patcher/vf1_people_pictures.py` (renderer),
    `patcher/vf1_picture_image.py` (image, PNG, the game's blitter).
  - **Family Tree Maker:** draws a family's tree from its save, with each face from the game, and lets you mark,
    colour, arrange and export it (PNG or JPG); it is the Virtual Villagers Fun Patcher's Family Tree Maker
    (matched to its main at cdcface3: no job or skill lines on portraits). With the Family History Log it also
    shows what the save forgets: divorced and dead spouses, earlier spouses after a remarriage, causes and ages of
    death, twins and triplets, each child's real parents, and the event that brought a child in (The Little
    Visitor, Adopt Outside Child, Spawn Child); without a log it uses the save alone and says what is not known.
    Labels under each portrait, each its own tick box: Founder, Heir, Husband N / Wife N (the order of marriages,
    by the spouse's own sex), Remarried, Divorced, Deceased, Adopted, Runner, twins, the Random Event ("Popup
    Event: The Little Visitor"), the career in the game's words ("Career: Pastry Designer, Novice"), Left home.
    A spouse lost before any child is drawn with their partner's couple line.
    The Family Member Info tab's **Relationships** list names everyone of one kind of relative to the selected
    member -- parents and children, full and half siblings, twins and triplets, grandparents and grandchildren of
    any generation ("Great-great-grandmother", then "3× great-grandmother"), aunts, uncles, nieces, nephews,
    cousins of any degree and removal, half and double forms, partners (the other parent of a child, and a spouse),
    in-laws and step-relations -- the dead and those no longer in the house marked; click a name to select them
    (read-only; `patcher/vf1_relationships.py`, a port of the Virtual Villagers tool's). Two living family members
    with the same name and looks are two people with their own edits (told apart by their place in the save's
    Family Tree); older edits that cannot be told to be either one's are kept in the file but not shown. A title
    line you retyped keeps your words with the counts and date of the tree now, and big trees are drawn faster
    with the same picture.
    Saves and logs are only read; the tree keeps its own tree file per save. Its ready-made backgrounds and logos
    are the owner's pictures in `patcher/tree_pictures`. Modules `patcher/vf1_genealogy.py`,
    `vf1_family_history.py`, `vf1_tree_memory.py`, `vf1_family_tree*.py` and helpers; tests
    `tests/test_family_tree.py`, `tests/test_family_tree_memory.py`, `tests/test_relationships.py`,
    `tests/test_tree_living_namesakes.py`, `tests/test_tree_big_speed.py`.
  - Every button, patch and setting has a small **"?"** beside it that opens a brief How to Use guide, written
    in `patcher/how_to_use.json`; `tests/test_how_to_use.py` refuses a patch or button without one. The
    Tools tab's *Getting started* link opens the overview.

The save tools live in `patcher/vf1_save_backup.py` (no Tk; tested with temporary copies only, see
`tests/test_save_backup.py` and `tests/test_tools_tab.py`) and the guides in `patcher/vf1_how_to_use.py`.

## Planned

- **Cut content:** restored where the game ships unused text or art.

Data the game itself does not track (the purchases, the Family page's choices, each tray outfit's picture)
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
  `native\build_logs.bat` builds `build\vf1logs.dll` (the Family History Log).
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
