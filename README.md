# Virtual Families 1 Patcher

A patcher for **Virtual Families** (Last Day of Work, 2014; PC version 1.01.00),
adding features from Virtual Families 2 and new cheats.

**Status: early research. Nothing is patchable yet.** See
[docs/FEASIBILITY.md](docs/FEASIBILITY.md).

## Planned features

All of these are reached from a new **Upgrades menu** button in the store.
They open as ordinary Windows dialogs, the way the Virtual Villagers Fun
Patcher works, rather than as in-game screens.

- **Cheat upgrades:** money, food, the bank interest rate and villager stats.
- **Roll the Dice:** start a random island event now.
- **Restored cut content**, where the game ships text or art that nothing
  uses.
- **Time controls.**
- **A Flea Market page** with every item.
- **Clothing and hairstyle changer**, with every option listed.
- **Same-sex marriage**, and rerolling dating candidates.
- **Baby spawn cheats** and an **adoption menu** for children.
- **Older Villager Mortality Curve:** a gentler old-age death roll, as in
  VF2.
- **Generation and Oldest Villager counters.**
- **Achievements** for the new features.

Data the game itself does not track (the counters, for example) is kept in
the patcher's own file next to the save, never inside the game's records.

## How it works

The VF1 executable ships no symbols, but Virtual Families 2 is the same
engine and a VF2 build leaked its object files. `tools/recover_function_names.py`
transfers function names from those objects to VF1 through RTTI vtables and
the call graph, and checks the result against VF1's own string table.
Patches will then hook VF1's executable directly, as the Virtual Villagers Fun
Patcher does.

This repository never contains game files. Tools take the paths of your own
copies as arguments.

## Related projects

- [Virtual Families 2 Restoration/Addition Patcher](https://github.com/Lorsieab2/Virtual-Families-2-Restoration-Addition-Patcher)
- Virtual Villagers Fun Patcher

## Requirements (research tools)

Python 3.11 or later, and `pip install -r requirements.txt`.
