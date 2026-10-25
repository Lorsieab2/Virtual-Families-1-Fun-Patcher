# Family Logs (vf1logs.dll): what is written, where, and how each event is seen

The Virtual Villagers Fun Patcher's logs, ported to Virtual Families 1 with family wording, as its own
companion DLL (one feature, one DLL). Experimental (default off) until it is tested in a running game.
Virtual Families 1 keeps no history (docs/vf1-save-format.md section 3), so every log is written by the DLL
at the moment the event happens, from the game's own memory; the words the game has are the game's own
(read from the executable's string table at run time: "Male", "Female", "Nursing", the six causes of
death 0x507..0x50C, "{name} is going to college!" 0x3AE, "New Generation" 0x1CA).

## Files (per save slot, beside the save; the Virtual Villagers patcher's per-save layout)

    <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\
        Family History\Family History <k>.txt                      every event, one line: "[YYYY-MM-DD HH:MM:SS] ..."
        Births and Conceptions\Virtual Families 1 Births and Conceptions Log <k>.txt
        Deaths\Virtual Families 1 Deaths Log <k>.txt
        Events\Virtual Families 1 Events Log <k>.txt
        Family Population\Family Population - Save <N>.txt         rewritten at each save
        Family Statistics\Family Statistics - Save <N>.txt         rewritten at each save
    <save folder>\Virtual Families 1 Patcher\Save <N>\Data\
        Parents\Virtual Families 1 Parents - Save <N>.dat          every child's mother and father (beyond the tree)
        Unaccounted Villagers\Virtual Families 1 Family Members at Last Save - Save <N>.dat
        Family Statistics\Family Statistics - Save <N>.dat         the Babies Born / Deaths counters
        Log Checks\Virtual Families 1 Backfill - Save <N>.dat      the once-only backfill marker

Every log file opens with `Family: <family name> (Save <N>)` (the VV logs' `Village: <name> (Save <S>)`).
Records are numbered per slot across files ("Conception <n>", "Birth <n>", "Death <n>", "Event <n>") and a file
rolls to the next number after 256 numbered records (the Family History after 2000 lines); nothing is ever
rewritten. Data files are text, tagged on their first line (`VF1LOGS PARENTS 1`, `VF1LOGS MEMBERS 1`,
`VF1LOGS STATS 1`, `VF1LOGS BACKFILL 1`), tab-separated, written atomically (temp file, then replace) except the
append-only Parents file. The slot is theGameState+0x1B188 for events and the Save/Load argument for snapshots.

- **New family** (the game's new-family adoption: StartNextGeneration with no generation before it, outside a
  load, not after Evict Family) and **Start Over** (the menu's confirmed call of theGameState::Restart) delete
  everything in `Save <N>\` except a `Backups` folder in it, then every log is created with its header.
- **Existing family, first load**: every log is created if absent; the Family Tree's generations (parents, children,
  deaths the tree records with a slot of -1) are written to the Family History as `[backfilled, no date] ...`, the
  children's parents to the Parents file, the counters' baseline from the tree and the game's own baby count (less
  the unborn), then the marker; never twice (the marker, or a Family History that already holds lines).
- **Evict Family** keeps the slot's logs: the eviction is an Event, and the next family's first generation is
  logged as "after the eviction".

## Check Saves & Logs / Repair Saves & Logs (patcher/vf1_log_tools.py, the Tools tab)

Check reads every file above against the save (and `Virtual Families<N+20>.ldw` / `<N+40>.ldw` when they hold
the same family) and writes nothing. Repair, with the game closed and only what the player ticked or answered,
writes in the same slot folder (so Start Over and a new family clear these too):

    Save <N>\Logs\Repairs Made\Virtual Families 1 Repairs Made Log <k>.txt   "Repair <n>": every change, the lines
                                                                           removed (with the reason), every answer,
                                                                           each file's copy, the backup folder
    Save <N>\Logs\Unaccounted\Virtual Families 1 Unaccounted Log <k>.txt     "Unaccounted <n>": a family member gone
                                                                           with no record of how
    Save <N>\Logs\Reconciliation\Virtual Families 1 Reconciliation - Save <N>.txt   the check, as it stood before the
                                                                           latest repair
    Save <N>\Data\Log Checks\Virtual Families 1 Answered Questions - Save <N>.dat   `VF1LOGS ANSWERS 1`, then one JSON
                                                                           answer per line (never "Don't know")
    Save <N>\Copies Made Before Repairs\Repair <n> <date>\...              each file as it was before repair <n>

and before anything, a backup of the whole save folder, `Backups\Backup <date> (before repair)` (Restore Saves
lists it). Repairs append to the logs as the DLL does (same numbering, same rolling) except removals, which
rewrite the file only when it still holds exactly the lines checked. The DLL reads none of these new files.
The save is never written.

## Hooks (each traced in the vanilla disassembly and proved by tools/vf1_logs_sites.py; emulated in tests)

| Event | Where | Kind | Why it is enough |
|---|---|---|---|
| Conception | 0x48EBB2 call of CVillager::Impregnate 0x4864D0 | call retarget (chains vf1fun's wrapper) | its only caller; the father is the patriarch whose head/body the step passes (0x48EB99..0x48EBA8) |
| Birth (single, twins, triplets) | 0x424F93 call of the physiology pass 0x48BC90 | call retarget | its only caller; the only delivery (0x48C073..0x48C307) and the only write of 0 to the pregnancy field (0x48C2EE) are inside it; the DLL compares before and after |
| Death + cause | 0x48E200 and 0x489D8F calls of CFamilyTree::ReportDeath 0x481CF0 | call retargets | its only two callers; the cause is CVillagerState+0x10, written only by SetHealth 0x48F820 / AdjustHealth 0x48F860 when health reaches 0; logged once per villager (slot, name, sex, age), also across sessions (the members file) |
| Marriage | CFamilyTree::UpdateParents 0x4819C0 | entry (8 bytes stolen) | the Marry button (0x438337) and vf1fun's same-sex wedding both call it |
| New family, Next Generation, Adopt New Person | CFamilyTree::StartNextGeneration 0x481B30 | entry (chains vf1kids' jmp) | StartFamilyTree (0x481E11), the adoption accept (0x4368E6) and vf1fun's Adopt New Person reach it |
| A child joins | CFamilyTree::AddOffspring 0x481AA0 | entry (chains vf1kids' jmp) | Little Visitor, Spawn Child, Adopt Outside Child; Impregnate's own calls (the babies) are told apart by the return address |
| Leaving home | CVillager::SetLeftHome 0x4857F0 | entry (8 bytes stolen) | age 19 (0x489EC5), the island event (0x418F46), Boarding School |
| Start Over | 0x448426 call of theGameState::Restart 0x4243C0 | call retarget | its only caller |
| After save / load | theGameState vtable 0x4B5E6C / 0x4B5E68 | vtable (chains vf1fun) | as vf1fun's own per-slot files |
| Roll the Dice, Divorce Spouse, Evict Family, Adopt New Person, Spawn Child, Adopt Outside Child, Boarding School | vf1fun.dll calls `VF1Logs_Event` | export | vf1fun's own functions, before they change anything |

SetHealth 0x48F820 is not hooked: the cause it stores is read at ReportDeath, which is simpler and sees every death
(also AdjustHealth's). vf1fun loads this DLL after vf1kids.dll, so vf1kids' pins are checked before anything here
is written; a hooked entry that already holds another companion's jmp is chained to it.

## Live checks still pending (nothing here has run in the game)

- A real conception, birth (single and twins), death (both report paths), marriage, Next Generation, Adopt New
  Person, left home, and each vf1fun event, written with the right names and in the right slot folder.
- theGameState+0x1B188 holding the new slot when a brand-new family is adopted (the wipe uses it).
- The start-up's loads of slots 1..5 backfilling each slot from its own save (memory then holds that slot's family).
- The words GetString returns in the running game (the string manager is built at run time).
- Windows file behaviour (a log held open by another program; long paths) and performance of the per-record
  file scan on long-lived families.
