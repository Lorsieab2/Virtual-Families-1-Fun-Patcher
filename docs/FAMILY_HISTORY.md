# The Family History log (vf1logs.dll): every record, where it is written, and how each event is seen

One log, the **Family History**, of every family event Virtual Families 1 has, for the Family Tree Maker (the save
forgets a spouse who leaves or dies before any child, every earlier spouse, twins and triplets, causes of death and
how anyone joined or left). The patch **Family History Log** (setting `FamilyHistory`, a Main Patch, on by default
since 26 October 2026, ticked by Enable All) installs its own DLL, `vf1logs.dll`, which writes each event as it happens, from the
game's own memory and with the game's own words (the executable's string table, read at run time with `GetString`:
"Male", "Female", "Nursing", the six causes of death 0x507..0x50C, "{name} is going to college!", "New Generation",
every e-mail subject and pop-up title). The layout is the Virtual Villagers Fun Patcher's records (its Births,
Deaths, Arrived and Island Events records), with family words. In Virtual Families the game's random events are
**Random Events**, each an **Email Event** or a **Popup Event**.

## The file (per save slot, beside the save)

    <save folder>\Virtual Families 1 Patcher\Save <N>\Logs\Family History\Family History <k>.txt

It opens with `Family: <family name> (Save <N>)`. Each record is a heading `[YYYY-MM-DD HH:MM:SS] <Kind> <n>`
(numbered per kind across all files, as the Virtual Villagers logs number theirs), its `  Label: value` lines (a
family member's own lines one step further in), then a blank line. A family member is written as the Virtual
Villagers patcher writes a villager: the name, then the age (in years), sex, head and body. Nothing is rewritten;
after 2000 records the next one opens file `<k+1>`. The slot is theGameState+0x1B188 (the Load argument at a load).

## Every record

```
[2026-10-24 12:34:56] Conception 1        [2026-10-24 12:34:56] Birth 1
  Mother: Ann                               Child: Cid
    Age at conception: 26                     Sex: Male
    Sex: Female                               Head: 3
    Head: 3                                   Body: 4
    Body: 4                                 Mother: Ann
  Father: Bob   (or "Father: (unknown)")      Head: 3
    Age at conception: 27                     Body: 4
    Sex: Male                               Father: Bob   (or "Father: (unknown)")
    Head: 7                                   Head: 7
    Body: 8                                   Body: 8
  Babies Nursing: 2                         Born as: Single birth | Twin | Triplet
  Generation: 1                             Generation: 1

[...] Death 1                             [...] Marriage 2
  Name: Bob                                 Family member: Ann
  Age at death: 27                            Age: 26
  Sex: Male                                   Sex: Female
  Cause of death: Old age                     Head: 3
  Head: 7                                     Body: 4
  Body: 8                                   Married: Carl
  Family role: Parent (married in)            Age: 29
  Generation: 1                               Sex: Male
  Current spouse of Ann: (none)               Head: 5
                                              Body: 6
[...] Divorce 1                             Remarried: yes                       (a remarriage only)
  Family member: Ann                        Earlier spouse: Bob (died|divorced)  (a remarriage only)
    Sex: Female                             Current spouse of Ann: Carl
    Head: 3                                 Generation: 1
    Body: 4
  Divorced: Bob                           [...] Arrived 1
    Age: 27                                 Name: Wren
    Sex: Male                               Age at arrival: 3
    Head: 7                                 Sex: Female
    Body: 8                                 Head: 3
  How: Divorce Spouse                       Body: 4
  Current spouse of Ann: (none)             How: Adopted (Popup Event: The Little Visitor)
  Generation: 1                                  | Adopted (Adopt Outside Child) | Spawn Child (then "  Parents:",
                                                   "    Mother: Ann", "      Head: 3", "      Body: 4", "    Father: ...")
[...] Left Home 1                           Family role: Child
  Name: Eve                                 Generation: 1
  Age: 19
  Sex: Female                             [...] Random Event 1
  Head: 3                                   Popup Event: The Little Visitor     (or "Email Event: Subject: Tax Audit")
  Body: 4                                   Choice: A                           (an event with choices: A or B)
  What happened: Eve is going to college!   Generation: 1
     | Left home with The Talent Scout (Popup Event)
     | Sent to Boarding School | Left the house (Popup Event: <title>)

[...] Generation 1 / New Generation 1 / Generation 2
  Name: Ann
  Age: 26
  Sex: Female
  Head: 3
  Body: 4
  How: Founder (adopted and started the family) | Founder (after the eviction) | Heir (inherited the house)
     | Adopt New Person
  Generation: 1

[...] Roll the Dice 1          [...] Evict Family 1                  [...] Start Over 1
  Cost: $500                     Family members: Ann, Bob              The earlier family's history was cleared.
  Popup Event: Adoption Day      Generation: 1
  Generation: 1

[...] Family Renamed 1         (written by Rename Family on the Tools tab)
  Old name: Smith
  New name: Brand New

[backfilled, no date] Family Tree 1      (an existing family's first load, once: what the save's tree holds)
  Parent: Ann                    (Sex, Head, Body one step in; "    Died: yes" for a slot of -1)
  Parent (married in): Bob
  Child: Cid
  Current spouse of Ann: Bob     (the newest generation, both alive)
  Generation: 1
  Note: Recorded afterwards (from the save's Family Tree: no dates, ages, causes, twins or earlier spouses)
```

The two mails that are not one of the 71 events are Email Events too: `Email Event: A marriage proposal (the dating
e-mail)` and `Email Event: A letter from a child who left home`.

- **New family** (StartNextGeneration with no generation before it, outside a load, not after Evict Family) and
  **Start Over** (the menu's confirmed call of theGameState::Restart) delete everything in `Save <N>\` except a
  `Backups` folder in it; the new family's log opens with `Start Over 1` (after a Start Over) and `Generation 1`.
- **Evict Family** keeps the log: everything before the `Evict Family` record belongs to the family that left.

## Hooks (each traced in the vanilla disassembly, proved by tools/vf1_logs_sites.py, emulated in tests/test_family_history.py)

Every hook is **VERIFIED-E**: the shipped DLL itself runs in unicorn with the real game code, each hook reached
from a live caller (tests/history_scenarios.py lists what runs for real and every stand-in).

| Records | Where | Kind | Evidence |
|---|---|---|---|
| Conception | 0x48EBB2, the only call of CVillager::Impregnate | call retarget (chains vf1fun's wrapper) | the try-for-a-baby step passes the patriarch's head/body (0x48EB99..0x48EBA8) and the constant name "Joey" (0x48EBA9): the father is the patriarch with that head and body. Emulated from the step itself |
| Birth (single, twin, triplet) | 0x424F93, the only call of the physiology pass 0x48BC90 | call retarget | the only delivery (0x48C073..0x48C307) and the only write of 0 to the pregnancy field (0x48C2EE) are inside it. The father: the one seen at conception this session, else the record's other parent whose head and body equal the mother's +0x2AD0 / +0x2ACC (Impregnate stores them, 0x48653F..0x486559), else "(unknown)". Emulated: single, twins, triplets, after a load, and with the father gone |
| Death | 0x48E200 and 0x489D8F, the only calls of ReportDeath 0x481CF0 | call retargets | the cause is CVillagerState+0x10, stored only by SetHealth 0x48F820 / AdjustHealth 0x48F860; each caller sets present 0 right after (0x48E233, 0x489D8B), so a death is reported once. Emulated both paths |
| Marriage, remarriage (any sexes) | CFamilyTree::UpdateParents 0x4819C0 | entry (8 bytes) | the Marry button (0x438337) and vf1fun's same-sex wedding (Cheat Upgrades) call it; the spouse is the one it writes into parent 2. The earlier spouse and why they left: the slot's own log (a Death or Divorce record of them after their Marriage record). Emulated: opposite-sex, same-sex (as vf1fun calls it), after a childless death (the real ReportDeath frees parent 2) and after Divorce Spouse |
| Generation, New Generation | CFamilyTree::StartNextGeneration 0x481B30 | entry (6 bytes, chains vf1kids' jmp) | its only stock callers: the adoption scene's accept 0x4368E6 (Next Generation: the heir and their place) and StartFamilyTree 0x481E11 (a new family); vf1fun's Adopt New Person calls it with -1. Emulated from the adoption scene's own accept (0x4368DD) and as vf1fun calls it |
| Left Home | CVillager::SetLeftHome 0x4857F0 | entry (8 bytes) | its only stock callers: AllVillagersTimeflowUpkeep at 19 (returns to 0x489ECA: college) and The Talent Scout's ImpactGame (0x418F4B); vf1fun's Boarding School tells the DLL first. Emulated from 0x489EC3, from the Talent Scout's own dialog, and as vf1fun calls it |
| Random Event (Email Event / Popup Event), Arrived and Left Home with it | 0x41B2C5, the event chooser's only call of ldwDialog::DoModal 0x401B10 | call retarget | the chooser 0x41B1F0 is reached only from FireEvent 0x41B360 (pop-up: the main scene 0x445353, and vf1fun's Roll the Dice) and FireEmailEvent 0x41B3A0 (an opened e-mail, 0x44507D); it is the only caller of the dialog's constructor 0x41A970, which keeps the event at +0x50 and GetString(GetTitle()) at +0x54; the draw 0x419D70 prints +0x54 as the title, laid out as an e-mail when the event's vtable +0x14 is true (Email Event, else Popup Event). The choice is +0x830 (0 A, 1 B), read when the event's vtable +0x10 (has choices) is true. DoModal runs with "update the parent" 0 (0x41B2C2), so only the dialog's handler 0x41B0A0 (ImpactGame on OK) changes the family during the call: a member who appears is Arrived ("Adopted (Popup Event: <title>)"), one who goes is Left Home. Emulated from both live callers for every event the test house can fire (59 of 71), choice A then OK through the real handler; each title is the executable's text, checked against docs/game-mechanics/events_registry.tsv |
| Email Event: the dating e-mail, the letter | 0x445023 (the dating scene's switch 0x440E60) and 0x445030 (the only call of the letter 0x415B60) in the main scene's mail branch | call retargets | the branch tells the mail types apart: 2 (0x445002), 3 (0x44502A), else an event (0x44503A). Emulated from 0x445007 and 0x44502F |
| Start Over | 0x448426, the only call of theGameState::Restart 0x4243C0 | call retarget | emulated: the slot folder is emptied, Backups kept, and the next family's log says so |
| After a load | theGameState vtable Load slot 0x4B5E68 | vtable (chains vf1fun) | emulated, also over a vf1fun-style handler; the backfill on copies of real saves |
| Divorce, Evict Family, Arrived (Spawn Child, Adopt Outside Child), Roll the Dice, Boarding School | vf1fun.dll calls `VF1Logs_Event(kind, who, a, b)` | export | vf1fun's own functions, before they change anything (Divorce before the spouse leaves, Evict before the tree is reset, Boarding School before SetLeftHome); Roll the Dice after the event it fired |

Found while tracing (stock game, not changed): **Landscaping Service (60) and Housekeeping Services (61) are never
shown.** Each has choices and a CanFire that returns true without choosing a villager (0x417FE0), so GetTarget
(0x4173C0) returns 0 and the dialog's constructor skips showing it (0x41AAE1..0x41AAF1 leave +0x4C at 0); the chooser
then returns false and nothing happens (VERIFIED-C; VERIFIED-E with the constructor's stand-in). Events 1, 4, 25, 26,
37, 38, 39, 42, 43 and 63 could not fire in the test house (their CanFire was false there); their titles are
checked, not their run.

The death behaviour's second removal (0x48E217..0x48E22D) is **not a family member** (VERIFIED-C): the dying
villager's +0x1353C is the slot of a copy of them that 0x48B380, called at 0x48E1CA, makes for the death behaviour (it
copies the whole 0x145FC-byte villager into a free slot and marks the copy present); the behaviour's end takes the
copy away again. Nothing is logged for it.

## UNCONFIRMED

- After Next Generation the adoption scene runs a loop over every villager (0x4368EB..0x436907; the Game Mechanics
  spec: it "hides every other villager"). Who leaves the household there is not logged as Left Home.
- Where the game shows "Babies Nursing" and the career level words on screen is not traced (they are its strings).

## Live checks still pending (nothing here has run in the game)

- Every record above written in the right slot folder in a running game, with the game's own words.
- theGameState+0x1B188 holding the new slot when a brand-new family is adopted (the wipe uses it).
- The start-up's loads of slots 1..5 backfilling each slot from its own save.
- Windows file behaviour (a log held open by another program; long paths).
