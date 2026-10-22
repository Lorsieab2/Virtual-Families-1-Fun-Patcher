# Up to 28 Children (vf1kids.dll): design, pins and evidence (static and emulated, no live test)

The owner's request (2026-10-21): up to 28 children per generation. Only the first 6 appear in the
Family Tree; every child, the 7th to the 28th included, can be chosen to inherit the house in Next
Generation. Children the save cannot record are kept in a `.dat` sidecar beside the save (the Virtual
Villagers patcher's convention); the save format does not change. Twins and triplets near the limit are
clamped (27 children: a twin or triplet pregnancy has one baby; 26: a triplet pregnancy has two), never
past 28. It is the Virtual Families 2 patcher's Up to 28 Children (its `docs/b200-up-to-28-children.md`)
on VF1's own code, as its own DLL.

## Where the vanilla game limits children

All addresses are the vanilla `Virtual Families.exe` (SHA-256 5db828c3...4487, image base 0x400000, no
ASLR). `research/villagers.md` sections 1b and 6 found them; `tools/vf1_kids_sites.py` re-proves every
one with capstone + pefile.

| What | Address | Evidence |
|---|---|---|
| Household slots | CVillagerManager 0x5B8898, FindEmptySlot 0x489C70, GetVillager 0x489900 | `cmp eax,1Eh`: 30 slots, villager i at +0x14640 + i * 0x145FC |
| Family Tree record | CFamilyTree 0x5AB908, AddOffspring 0x481AA0 | +0 count, records of 0x6C8 from +4; child count at record + 0x1B4, `cmp ecx,6; je refuse`; six 0xD8 child records end exactly at the next record |
| Births | EmptyOffspringSlots 0x4816E0 | `6 - count` (6 with no family) |
| Twins / triplets | CVillager::Impregnate 0x4864D0 | first call EmptyOffspringSlots (none = no pregnancy); twins only when it is > 1, triplets only when it is > 2; chances GetRandom(100) < 7 + bonus and < 25 + bonus. vf1fun's pregnancy one-shots retarget only the two rolls and the first baby's gender, so the same caps apply to them |
| Next Generation | CAdoptionScene CreateNextGenerationCandidates 0x436390, GetNextCandidate 0x436460, Activate 0x436700, HandleMessage 0x436780 | clones every recorded child as an adult into six-dword arrays (+0x14 clones, +0x2C sources, +0x44 count, +0x48 cursor); Accept calls StartNextGeneration(scene[+8], scene[+0x2C + 4 * scene[+0x48]]) and hides every other slot |

**On the owner's description sentence** ("Virtual Families 1 natively keeps up to 6 children per generation in its Family Tree, and a household holds at most 30 villagers (2 parents and 28 children). This patch keeps children 7 to 28 in a separate file beside the save, so they never overwrite Family Tree entries; storing more than 6 children in the Family Tree itself would overwrite its entries and glitch the game."): it matches the disassembly. The household is 30
villager slots (KIDS_HOUSEHOLD_SLOTS 0x1E), and the Family Tree record holds 2 parents + **6** children per
generation; a 7th child written into it would overwrite the next generation's record. Past 30 villagers
nothing is overwritten: FindEmptySlot returns -1 and no villager is spawned.

## What the patch does

vf1fun.dll loads `Virtual Families 1 Patcher Files\vf1kids.dll` (installed only while the
`UpTo28Children` setting is on) at the end of its own start-up and calls `VF1Kids_Startup()`. The DLL
compares every pinned function with the vanilla bytes (call displacements excepted, because vf1fun
retargets some of those calls) and installs nothing on a difference. Then eleven entry hooks, each a
5-byte jmp, with trampolines of the stolen whole instructions: EmptyOffspringSlots (replaced:
min(28 - children recorded this generation, free household slots)), AddOffspring (stock below 6, an extra
entry from the 7th on), CountSurvivingChildren (stock + living extra children: VF1 counts a child while
its record slot is not -1), ReportDeath, ChangeName, Reset, StartNextGeneration, the two Next Generation
candidate functions (one adult clone at a time; in a full house the clone is made in the child's own
slot and the child is put back byte for byte, also around any save), and theGameState::Save / Load.

vf1fun's Family page shows "Children: N of 28" while the DLL is installed (the two numbers come from
the DLL's `VF1Kids_Children` and `VF1Kids_Limit`), and its Spawn Child / Adopt Outside Child refusal says
"This family has no room for another child (28 at most)." instead of "six children".

## The sidecar

`<save folder>\Virtual Families 1 Patcher Data\Children\<save file>.dat`, beside the save file the game
writes (`ldwGameState::MakeGameStatePath`, theGameState vtable +0x0C). Same format as the VF2 port with
the tags `VF1KIDS` / `VF1V101`: the FNV-1a 64 of the save file it belongs to, generation count, parent 1,
and one 64-byte entry per extra child (slot, gender, state, head, body, age, name). Written atomically
after each save of slots 1..5 with extra children; the game's backup of the previous save (slot + 20) gets
the previous sidecar; after a load the sidecar whose hash matches the loaded file is used; an unreadable
file is kept as `<name>.unreadable-N.dat`.

Before each save both sidecars are read and checked against the save files beside them. Only a sidecar
that validates and was written with its save is rotated with it (or removed with it, at slot + 20); a
damaged one, or one that validates but belongs to another save, is renamed `<name>.unreadable-N.dat` and
never deleted. If even that rename cannot be made, the file is left exactly as it is and no sidecar is
written over it. A sidecar another program holds open (sharing, lock or access-denied errors) is not
damaged: the open is tried five times over about a second; if it stays shut it is left as it is, never set
aside, and no save writes or rotates this slot's sidecar until it has been read. The first save that can
read it keeps every child it records together with the ones born since.

## Evidence

- `tools/vf1_kids_sites.py`: 23 pins, the layout constants as operands, the calls the DLL relies on, the
  stolen bytes (whole, position-independent, no branch into them), CloneAsAdult never writing the slot
  index, MakeGameStatePath formatting `%s%d.ldw` and sitting at theGameState vtable +0x0C.
- `tests/test_up_to_28_children.py` with `tests/kids_scenarios.py` (unicorn, the REAL DLL with the REAL
  vanilla code): 28 children recorded, the 29th refused; the free-slot cap; deaths counting toward 28;
  renames and reused slots; single / twin / triplet pregnancies at 26, 27 and 28 children through the real
  Impregnate (and with free slots, so the 28 alone limits); the stock odds; Next Generation offering every
  child, the six-or-fewer stock path, the full house; the sidecar round trip, the backup, an unreadable
  file kept aside, another family; an unreadable and a foreign backup sidecar set aside (never deleted,
  never rotated); a shut sidecar retried (sharing, lock and access-denied errors) and never set aside or
  replaced; the longest save path set aside or left in place; the setting off; a patched pinned function
  refusing the whole plan; 22 source mutations each caught; vf1fun's loader in a harness with a stand-in
  DLL.

## Differences from the request, and what is not covered

- An heir chosen from the 7th-28th children has no line to a parent in the Family Tree; a stock child heir
  keeps its line.
- The patcher achievements that look at Family Tree records (Return of the Rainbow, Spiky!) do not see
  children 7-28.
- A lost sidecar loses the extra children's status (they stay in the house, but cannot inherit, and the
  limit is counted from the stock six again; the free-slot cap still holds).
- Experimental (the owner's decision, 2026-10-22): category `experimental` in the manifest, shown as the patcher's own **Experimental** section (red heading, after Optional Patches) with the warning "Experimental: not yet tested in a running game. Back up your saves before using it." It defaults off; Enable All and `--enable-all` leave Experimental settings off, so it is only ticked (or named with `--enable`) deliberately. tests/test_engine.py exempts the Experimental category by rule and fails if any other patch defaults off.
- No live test: the scene's drawing of a clone made in a child's own slot, the real CloneAsAdult (a seam in
  the emulation), real saves and loads, and Windows file behaviour are not exercised in a running game.
