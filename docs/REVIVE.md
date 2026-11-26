# Revive a Family Member (vf1revive.dll, the `Revive` setting)

The Virtual Villagers patcher's "Revive Buried/Disappeared Villagers", ported to Virtual Families 1. Built to the
owner's decisions of 2026-11-26 (one per line below). Not yet tested in a running game: see "Live checks".

## What the player sees

- Upgrades button, Family page, **Revive a Family Member (someone who died comes back)...**: a list of everyone of the
  family who died and is not back yet (name, age at death, cause, the age they come back at, "some details not
  known" for a backfilled person, "cannot now" with the reason). **Bring them back** asks, charges and brings them.
- **Price: $25,000** (`kRevivePrice`, native/vf1fun/family.inc, the one constant; the owner, 2026-11-26): above the
  game's dearest purchase (the third career room, $15,000) and Adoption Services ($4,000, a new child). Free while Free
  and Guaranteed Cheats is on, as every paid item.
- **Only the dead**: a snapshot is taken only at a death (both calls of CFamilyTree::ReportDeath, health 0). Divorce
  Spouse, The Talent Scout and Evict Family never call it, so they are never offered.
- **Age** (the owner, 2026-11-26, final): died younger than 20 -> back at the age they died at, in the game's own
  units (18 and 19 included); died at 20 or older -> back at exactly the game's 20-year mark (400 units), with their
  career, level and salary at death. Backfilled people follow the same rule; one whose age at death the backfill could
  not find is marked "unknown -> 20" and comes back at 20.
- **A grown-up with no career**: someone brought back at 20 (they died at 20 or older, or the age is unknown) who had
  no career is a grown-up all the same (the owner): never sent to college (at 20 they are past the at-19 exit, and the
  ageing pass's one HasCareer call that decides the leaving, 0x489EAC, answers "has a career" for them). A revived 18-
  or 19-year-old follows the game's own rules, the college exit included. **They can have babies** (the owner): a drop
  on the spouse's two career tests (0x44123D, 0x441250) answer the same, and the
  try-for-a-baby step's choice of mother and father (0x48EB40 GetMatriarch, 0x48EB4C GetPatriarch) runs the game's
  own rule with "has a career" true for them. Their career stays none; GetMatriarch / GetPatriarch's other callers
  (events, the dating scene) are the game's own. The Family History log's Conception record names such a father
  from the Family Tree (vf1logs.dll: the generation's parent at home, alive, a man, with the head and body the step
  passes) when the game's own GetPatriarch does not name him.
- **The same person**: name (a long name's whole name: the Names file gives back its short form), sex, head and body,
  the parents' names and looks, likes and dislikes, career (career, level and salary as at death: the game keeps no
  career history), fertility and "Wants kids?". **Moods and needs start fresh** (the game's own new villager), and
  health, the ageing clocks, pregnancy and the left-home flag are the new villager's.
- **Current generation only**: the snapshot's generation must be the tree's, and its family (parent 1 then, or the
  spouse who took parent 1's place after a childless founder died) must be the family now.
- **Family Tree**: a child of the generation gets their own entry back (its villager slot; the game then counts them
  as surviving again); a child 7..28 (Up to 28 Children) gets their vf1kids entry back (`VF1Kids_Revived`, no second
  place used); a parent gets their own entry back while it still waits (slot -1), or the empty spouse place when
  their partner of then is still parent 1; **a spouse whose partner has remarried comes back as a family member, not
  a spouse** (the owner, 2026-11-26): living in the house, in NO Family Tree entry (no child place, no effect on the
  child count, the heirs, Next Generation or Up to 28 Children), and **drawn on the game's Family Tree screen under the
  current spouse**: the screen's own spouse block (0x439D4C..0x439E7D: the frame image 0xC1, the name in the screen's
  font and colour, the portrait) is run once more at its end, for the current generation only, with a record of the
  DLL's own whose parent 2 is them and the y one parent step lower; the row's registers and frame are put back exactly.
  **Clicking them** opens the game's own person window, as clicking a tree person does: the row's click (0x4393E0, its
  only call 0x439B64) is the game's own first; when it hits nobody and the click is on their frame (the game's own
  test one step lower: the frame's rectangle, then its pixels), the same dialog (0x416CF0, DoModal, 0x4172E0) is shown
  with their record (their tree entry at death, with their name, looks and slot now).
- **Family History**: a `Revived <n>` record (docs/FAMILY_HISTORY.md); the Death record is never rewritten.

## The snapshot file

`<save folder>\Virtual Families 1 Patcher Data\Revive\Virtual Families<n>.ldw.dat`, one per save FILE (N, N+20,
N+40), never a new save field. The Up to 28 Children file's header (vf1kids.cpp) with its own tag: `VF1REVV\0`,
version 1, `VF1V101\0`, file size, the FNV-1a 64 hash and size of the save it was written with, generations, parent
1's slot and sex, the entry count (at most 64), the entries (2,256 bytes each), the FNV-1a 64 of everything before
it. Written with a temporary file and a replace right after `theGameState::Save(slot)`; rotated with the save
(N -> N+20 -> N+40) exactly as the Children file; read after a load only while the save beside it is the one it names
(else the N+20 file when it names this save; else, for another save of the same family, only the dead who are not
alive in this save). A file that fails its checks is set aside as `...unreadable-<k>.dat`, never deleted; a file
another program holds open is left as it is and never replaced. Back Up Saves, Restore, Copy / Move / Delete Player
Slot, Rename Family and Game Speed carry and re-match it as they do the Children file.

Each entry (`vf1revive.cpp` E_*, `vf1_revive_backfill.py` the same table): state (1 dead, 2 revived), source
(1 captured at the death, 2 a stale record in the save, 3 an older save, 4 a backup, 5 the Family Tree, 6 the Family
History log), a 2-bit mark per field (unknown / inferred / exact: name, sex, head, body, voice, name index, parents,
likes, dislikes, career, fertility, wants kids, age at death, cause, family tree, whole name, generation), the slot at
death, the family role, the generation, the log's death number, the capture time, the slot they came back in, then the
game's own blocks as at the death: CVillagerBio (0xA0), CVillagerState (0x98), the career (0x10), likes and dislikes
(0x18), their Family Tree entry and the generation's two parent entries (0xD8 each), and the whole name.

A revival writes back only the fields marked known; an unknown one keeps the new villager's own value. A snapshot
whose age at death is unknown comes back at 20. The entry also keeps how they came back (+44), so the grown-up rule
and the Family Tree screen still know them after a save and a load.

## Backfill (Tools tab, Revive Backfill)

`patcher/vf1_revive_backfill.py`: for every save file of every slot, in the save folder and in each
`Backups\Backup ...` folder, a snapshot of each family member the save's Family Tree marks dead (slot -1) or the
Family History log has a Death record for (made before that save, not alive in it), from the richest read-only
source, in this order:

1. their stale villager record in the save itself (health 0, cause kept): every field exact;
2. an older save (the game's N+20 / N+40, the other backups): a stale dead record there (exact), else the newest
   copy made while they were alive: identity exact, likes, dislikes, career, fertility and "Wants kids?" inferred;
3. the Family Tree entry: name, sex, head and body exact, the rest unknown;
4. the log (age at death in years: inferred to the unit; the cause: exact) and the Names file (the whole name).

It never writes a save or a log. A replaced file is copied first to `Revive\Before Backfill <date>\`; if any write in
a folder fails, every file written there is put back. A damaged file, or one naming another save, is left as it is.
A second run changes nothing; a snapshot captured at the death always wins. The backup folders are repaired while
the game runs; the live save folder waits until the game is closed (the running game rewrites its own file at its
next save).

## Hooks (tools/vf1_revive_sites.py proves them on the vanilla exe; tests/test_revive.py runs them)

| What | Where | How |
|---|---|---|
| a death | 0x48E200 (death behaviour's end), 0x489D8F (body removal): the only calls of ReportDeath 0x481CF0 | call retarget, chained to what is there (vf1logs.dll's wrapper or the stock function); the snapshot is taken first |
| after a load / around a save | theGameState vtable Load 0x4B5E68, Save 0x4B5E6C (SaveCurrentGame 0x4238E0 saves 0, slot, slot + 20 through it) | vtable slot, chained (vf1fun.dll hooks them first) |
| bringing someone back | CVillagerManager::SpawnPeepFull 0x48B2E0 | called, as vf1fun's Spawn Child does |
| the at-19 college exit | 0x489EAC, the ageing pass's HasCareer (0x48F080) call before the leaving (test eax / jne 0x489EE4) | call retarget: "has a career" for a revived grown-up (back at 20), the game's answer for everyone else |
| the Family Tree screen | 0x439E7D, the end of the tree row's spouse block (a 6-byte `mov eax, [esi+80h]`); 0x439B64, the screen's call of the row click 0x4393E0 | a jmp to the DLL (it runs that mov itself); a call retarget: the game's click first |
| who may have a baby | 0x44123D / 0x441250 (a drop on the spouse: HasCareer for both), 0x48EB40 / 0x48EB4C (the try-for-a-baby step: GetMatriarch, GetPatriarch) | call retarget: the same answer; the parents chosen by the game's rule with a revived grown-up counted as having a career (the game's own function when there is none) |

## UNPROVEN, and live checks

Nothing here has run in the game yet. Not proved safe until a live check:

- Writing the persistent fields over a freshly made villager (no sprite or behaviour state is re-derived from head,
  body or voice after CVillager::Init: Change Appearance relies on the same).
- A child brought back in their old tree entry: Next Generation and the heir list with them in it.
- A revived child, or a revived 18- or 19-year-old, with no career follows the game's own rules (at 19 with no career
  they leave home). Someone back at 20 with no career stays at home and can have babies.
- A spouse brought back as the spouse: the record's "a parent died" flag stays as the death set it.
- How a remarried partner's late spouse looks under the current spouse on the Family Tree screen: the frame one parent
  step below the spouse's, inside the screen and its scrolling (the last generation's row is the lowest; whether the
  scroll range reaches below it is not proved), and their person window when clicked.
- A family member outside the Family Tree: the game has no other such villager.
