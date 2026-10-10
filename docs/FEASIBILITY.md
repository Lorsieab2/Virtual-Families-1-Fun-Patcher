# Virtual Families 1 patcher: feasibility (2026-10-10)

All of this was found read-only, from the vanilla `Virtual Families.exe`
(1,146,880 bytes, PE timestamp 2014-06-09) and the Virtual Families 2 object
files that an old Steam build of VF2 shipped by accident.

## Verdict

**Feasible.** VF1 and VF2 are the same engine. Patching has to happen in the
executable itself, because no object files exist for VF1. The Virtual
Villagers Fun Patcher patches its five games the same way, with trampolines
and companion DLLs.

## Evidence

| Check | VF1 | VF2 |
| --- | --- | --- |
| Compiler (linker version) | 8.0 (Visual Studio 2005) | 8.0 |
| Built | 2014-06-09 | 2014-06-11 |
| Image base / ASLR | 0x400000, no ASLR | 0x400000, no ASLR |
| RTTI classes | 150 | 182 |

- **Shared classes:** 145 of VF1's 150 classes also exist in VF2. VF1-only:
  `theStoreScene` and four font classes.
- **No ASLR:** the image never moves, so patches can use fixed addresses.
- **Byte matching fails:** VF2's object files were compiled with different
  code generation from either shipped game, so only 14 VF2 object functions
  match VF1 byte-for-byte. Names have to be transferred structurally instead.

## Function names recovered

`tools/recover_function_names.py` (see its docstring) produces
`data/vf1_function_names.json`:

- **568 names from vtables.** RTTI in VF1 is paired with each VF2 object's
  vtable relocations.
- **Validated:** all 71 island-event `GetTitle` methods return the string id
  whose key is that event's own `eEvent...Title` in VF1's string table
  (`--strict`).
- **784 names after call-graph propagation** (2 conflicting addresses
  dropped).
- **VF1's string table:** 1,643 keys, in `data/vf1_string_keys.json`.

## Functions the wanted features need

| Feature | Found |
| --- | --- |
| Money cheats | `CMoney::Adjust` 0x422740 |
| Interest-rate cheat | `CMoney::UpdateInterest` 0x489a30 |
| Flea Market (give an item) | `CToolTray::AddItem` 0x4973e0 |
| Baby spawn, adoption | `CVillagerManager::SpawnSpecificPeep` (both overloads, 0x48b2e0 and 0x48bc60) |
| Adoption menu, Next Generation | `CAdoptionScene` methods, `CreateNextGenerationCandidates` 0x436390 |
| Dating / marriage candidates | `CDatingScene` methods |
| Group actions | `MakeAllVillagersDoIt` 0x48ab50, `GetVillager` 0x489900, `ldwGameState::GetRandom` 0x403650 |
| Roll the Dice | every island event's methods are named; the "fire an event" function is not yet located |
| Generation and Oldest Villager counters | `CAchievementsScene` draw and update methods are named |
| Mortality curve | not yet located; VF2 hooks the old-age roll inside `CVillagerManager`'s realtime physiology upkeep |
| Store "Upgrades" button | VF1's store is its own `theStoreScene`, not in VF2; it has to be analysed directly |

Every address here is a starting point. Each one must be confirmed by
disassembly before a patch depends on it.
