# The Family History log (vf1logs.dll): what is written, where, and how each event is seen

One log, the **Family History**, for the Family Tree Maker: the save forgets a spouse who leaves or dies before any
child, every earlier spouse, twins and triplets, and causes of death (docs/vf1-save-format.md section 3;
`CFamilyTree::UpdateParents` overwrites parent 2, `ReportDeath` 0x481CF0 drops a childless parent). The patch
**Family History Log** (setting `FamilyHistory`, Experimental, off by default, never ticked by Enable All) installs
its own DLL, `vf1logs.dll`, which writes them down as they happen, from the game's own memory and with the game's
own words (the executable's string table, read at run time with `GetString`: "Male", "Female", the six causes of
death 0x507..0x50C, every e-mail subject and pop-up title). Nothing else is logged and no data file is written.

## The file (per save slot, beside the save)

    <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\Family History\Family History <k>.txt

It opens with `Family: <family name> (Save <N>)`; every line is `[YYYY-MM-DD HH:MM:SS] <event>`. Nothing is
rewritten; after 2000 lines the next line opens file `<k+1>`. The slot is theGameState+0x1B188 (the Load argument
at a load).

| Event | Line |
|---|---|
| Marriage (the current spouse) | `Married: Ann (Female, 26) and Bob (Male, 27), generation 1` -- the first is the one already in the family |
| Remarriage | `Remarried: Ann (Female, 26) and Carl (Male, 29), generation 1; earlier spouse: Bob` |
| Divorce (the patcher's Divorce Spouse) | `Divorced: Bob (Male, 27) left the family, divorced from Ann, generation 1 (Divorce Spouse)` |
| Death | `Died: Bob (Male, 27), spouse, generation 1: Old age` (role: parent, spouse, child, not in the family tree) |
| Birth | `Born to Ann and Bob, generation 1: Cid (Male)` |
| Twins, triplets | `Twins born to Ann and Bob, generation 1: Cid (Male) and Dee (Female)`; `Triplets born to ...: A (Male), B (Female) and C (Male)` |
| A father the tree no longer holds | `Born to Ann and an unknown father, generation 1: Cid (Male)` |
| E-mail event | `E-mail: "Subject: Tax Audit"` (the subject line as the player sees it) |
| Pop-up event | `Pop-up: "The Little Visitor"; Wren (Female, 3) joined the family as a child, generation 1` |
| ... what it did to the family | `; <name> (<sex>, <age>) joined the family as a child, generation g` / `joined the household` / `left home` / `left the house` |
| Spawn Child / Adopt Outside Child (patcher) | `Joined: Max (Male, 7) as a child of Ann and Bob, generation 1 (Spawn Child)`; `Joined: Lil (Female, 5), adopted, generation 1 (Adopt Outside Child)` |
| Evict Family (patcher) | `Evicted: Ann, Bob left the house (Evict Family); the next family's history follows` |

- **New family** (StartNextGeneration with no generation before it, outside a load, not after Evict Family) and
  **Start Over** (the menu's confirmed call of theGameState::Restart) delete everything in `Save <N>\` except a
  `Backups` folder in it; the new family's log is created at once with its header.
- **Existing family**, at a load, when the slot's log holds no line yet: what the save's Family Tree holds,
  marked `[backfilled, no date]`: each generation's `Married: A (Female) and B (Male), generation g`, `Child: C
  (Male), generation g`, and `Died: N (Male), child, generation g` for each death the tree records (a slot of -1).
  Never twice (any line in any file stops it); a slot with no family gets no log.
- **Evict Family** keeps the log: everything before the `Evicted:` line belongs to the family that left.

## Hooks (each traced in the vanilla disassembly, proved by tools/vf1_logs_sites.py, emulated in tests/test_family_history.py)

Every hook is **VERIFIED-E**: the shipped DLL itself runs in unicorn with the real game code, each hook reached
from a live caller (tests/history_scenarios.py lists what runs for real and every stand-in).

| Event | Where | Kind | Evidence |
|---|---|---|---|
| Births, twins, triplets | 0x424F93, the only call of the physiology pass 0x48BC90 | call retarget | the only delivery (0x48C073..0x48C307) and the only write of 0 to the pregnancy field (0x48C2EE) are inside it; the DLL compares before and after. Emulated: Impregnate run from the conception step (0x48EB99), then the real delivery: single, twins, triplets |
| The father | the current record's other parent whose head and body equal the mother's +0x2AD0 / +0x2ACC | read | Impregnate 0x48653F..0x486559 stores the head/body it is given; its one caller (0x48EBB2) gives the patriarch's head +0x2A60 and body +0x2A64 and the constant name "Joey" (0x48EBA9, so the name is never the father's). Emulated, and "an unknown father" when the record no longer holds him |
| Deaths and causes | 0x48E200 and 0x489D8F, the only calls of ReportDeath 0x481CF0 | call retargets | the cause is CVillagerState+0x10, stored only by SetHealth 0x48F820 / AdjustHealth 0x48F860; each caller sets present 0 right after (0x48E233, 0x489D8B), so a death is reported once. Emulated both paths |
| Marriage, remarriage | CFamilyTree::UpdateParents 0x4819C0 | entry (8 bytes) | the Marry button (0x438337) and vf1fun's same-sex wedding call it; the spouse is the one it writes into parent 2. Remarriage: an earlier `Married:`/`Remarried:` line of the same person and generation in the slot's own log (after the last eviction). Emulated after a childless death (the real ReportDeath frees parent 2) and after Divorce Spouse |
| E-mail and pop-up events | 0x41B2C5, the event chooser's only call of ldwDialog::DoModal 0x401B10 | call retarget | the chooser 0x41B1F0 is reached only from FireEvent 0x41B360 (pop-up, from the main scene 0x445353 and vf1fun's Roll the Dice) and FireEmailEvent 0x41B3A0 (an opened e-mail, 0x44507D); it is the only caller of the dialog's constructor 0x41A970, which keeps the event at +0x50 and GetString(GetTitle()) at +0x54 (0x41AA2C..0x41AA3D); the draw 0x419D70 prints +0x54 as the title, laid out as an e-mail when the event's vtable +0x14 is true. DoModal runs with "update the parent" 0 (0x41B2C2), so its update (0x401C60) never runs the scene: only the dialog's own handler 0x41B0A0, which runs ImpactGame (+0x30 / +0x34) on OK, changes the family during the call. Emulated from both live callers for every event the test house can fire (59 of 71), choice A then OK through the real handler; each line's title is the executable's text, checked against docs/game-mechanics/events_registry.tsv |
| New family | CFamilyTree::StartNextGeneration 0x481B30 | entry (6 bytes, chains vf1kids' jmp) | StartFamilyTree (0x481E11), the adoption accept and vf1fun's Adopt New Person reach it. Emulated, also over a vf1kids-style entry jmp |
| Start Over | 0x448426, the only call of theGameState::Restart 0x4243C0 | call retarget | emulated: the slot folder is emptied, Backups kept |
| After a load | theGameState vtable Load slot 0x4B5E68 | vtable (chains vf1fun) | emulated, also over a vf1fun-style handler; the backfill on copies of real saves |
| Divorce Spouse, Evict Family, Spawn Child, Adopt Outside Child | vf1fun.dll calls `VF1Logs_Event(kind, who, parentA, parentB)` | export | vf1fun's own functions, before they change anything (Divorce before the spouse leaves, Evict before the tree is reset) |

Events found while tracing (stock game, not changed): **Landscaping Service (60) and Housekeeping Services (61)
are never shown**. Each has choices and a CanFire that returns true without choosing a villager (0x417FE0), so
GetTarget (0x4173C0) returns 0 and the dialog's constructor skips showing it (0x41AAE1..0x41AAF1 leave +0x4C at 0);
the chooser then returns false and nothing happens (VERIFIED-C, and VERIFIED-E with the constructor's stand-in).
Events 1, 4, 25, 26, 37, 38, 39, 42, 43 and 63 could not fire in the test house (their CanFire was false there);
their titles are checked, not their run. The type-2 e-mail (dating, opens the dating scene) and the type-3 letter
from a child who left home (composed text, no subject) are not island events and are not logged.

## Not logged

Conceptions, leaving home at 19, Next Generation, Adopt New Person, Roll the Dice and Boarding School (the tree
gets those from the save or does not need them). The death behaviour also takes a second villager out of the house
without a ReportDeath (the one named by the dying villager's +0x1353C, 0x48E217..0x48E22D); what that field holds is
UNCONFIRMED, so that removal is not logged.

## Live checks still pending (nothing here has run in the game)

- Every line above written in the right slot folder in a running game, with the game's own words.
- theGameState+0x1B188 holding the new slot when a brand-new family is adopted (the wipe uses it).
- The start-up's loads of slots 1..5 backfilling each slot from its own save.
- Windows file behaviour (a log held open by another program; long paths).
