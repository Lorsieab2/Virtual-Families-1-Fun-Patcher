# Revive a Family Member (vf1revive.dll, the `Revive` setting)

The Virtual Villagers patcher's "Revive Buried/Disappeared Villagers", ported to Virtual Families 1. Built to the
owner's decisions of 2026-11-26 (one per line below). Not yet tested in a running game: see "Live checks".

## What the player sees

- Upgrades button, Family page, **Revive a Family Member (someone who died comes back)...**: a list of everyone of the
  family who died and is not back yet (name, age at death, cause, the age they come back at, "some details not
  known" for a backfilled person, "cannot now" with the reason). **Bring them back** asks, charges and brings them.
- **Price: $10,000** (`kRevivePrice`, native/vf1fun/family.inc, the one constant): between the second career room
  ($5,000) and the third ($15,000, the game's dearest purchase), above Adoption Services ($4,000, a new child). Free
  while Free and Guaranteed Cheats is on, as every paid item. **The owner confirms the price before any release.**
- **Only the dead**: a snapshot is taken only at a death (both calls of CFamilyTree::ReportDeath, health 0). Divorce
  Spouse, The Talent Scout and Evict Family never call it, so they are never offered.
- **Age**: died at 18 or older -> back at exactly the game's 18-year mark (360 age units); died at 17 or younger ->
  back at the age they died at, in the game's own units. Backfilled people follow the same rule.
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
  a spouse** (in the house, not in the Family Tree).
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
whose age at death is unknown is refused (the age they would come back at is not known).

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

## UNPROVEN, and live checks

Nothing here has run in the game yet. Not proved safe until a live check:

- Writing the persistent fields over a freshly made villager (no sprite or behaviour state is re-derived from head,
  body or voice after CVillager::Init: Change Appearance relies on the same).
- A child brought back in their old tree entry: Next Generation and the heir list with them in it.
- A 5..17-year-old or an 18-year-old with no career: they grow up as any child (at 19 with no career they leave
  home). An 18-year-old with a career is an adult at once (the game's matriarch / patriarch rule is the career).
- A spouse brought back as the spouse at 18: the record's "a parent died" flag stays as the death set it.
- A family member outside the Family Tree (a remarried partner's late spouse): the game has no other such villager.
