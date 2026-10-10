# Virtual Families 1 Patcher

A patcher for **Virtual Families** (Last Day of Work, 2014; PC version 1.01.00),
adding features from Virtual Families 2 and new cheats.

## What's in v0.1.0

The store gets a new **Upgrades** button, next to Done. It opens ordinary
Windows dialogs, the way the Virtual Villagers Fun Patcher works:

- **Cheat Upgrades:**
  - add or set money;
  - add or set food;
  - change the bank's interest rate, which is remembered between sessions.
  - Cheat money doesn't count toward the money achievements.
- **Villager Cheats:** for one villager or everyone:
  - max health;
  - cure illnesses;
  - max happiness;
  - max energy;
  - fill up (Fed).
- **Flea Market:** every tray item the store sells, to buy or get for free.
- **Roll the Dice:** costs $500, and an island event happens right away,
  through the game's own event system.

Players: see [release/How to Use.txt](release/How to Use.txt).

## Planned

- **Store cheats:** price multipliers.
- **Weeds and trash:** spawn and clean-up cheats.
- **Helpers:** "Maid" and "Gardener" upgrades that keep the house and yard
  clean.
- **VF2-style purchases:** Health Plan, Food Club, Lucky Rock and Brokerage
  Account.
- **Time controls.**
- **Clothing and hairstyles:** change a villager's look, with every option
  listed.
- **Marriage and family:**
  - same-sex marriage;
  - reroll dating candidates;
  - divorce spouse;
  - evict family.
- **Babies and adoption:**
  - baby spawn cheats;
  - an adoption menu for children;
  - adopt a new person after the "you lost your family" game over.
- **Lifespan:** VF2's Older Villager Mortality Curve.
- **Counters:** Generation and Oldest Villager.
- **Cut content:** restored where the game ships unused text or art.
- **Achievements** for the new features.

Data the game itself does not track (the counters, for example) will be kept in
the patcher's own files, never inside the game's records.

## How it works

The patcher writes a patched **copy** of the game into a new folder. The
original game folder is never changed. The patched executable gets one small
loader:
- it lives in its own read-and-execute section;
- its state lives in a separate read-write section;
- it is entered from two places: game start-up and the store screen.

The loader loads `Virtual Families 1 Patcher Files\vf1fun.dll` by full path.
If that DLL is missing, the game runs exactly as normal.

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
  `outputs/VF1-Patcher-VERSION.zip`.
- **Tests:** set `VF1_VANILLA_EXE` to your own vanilla `Virtual Families.exe`,
  then run `pytest tests`.

## Related projects

- [Virtual Families 2 Restoration/Addition Patcher](https://github.com/Lorsieab2/Virtual-Families-2-Restoration-Addition-Patcher)
- Virtual Villagers Fun Patcher
