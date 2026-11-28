# Skin Tones (vf1skin.dll): design, pins and evidence (emulated, no live test)

The owner's decisions (2026-11-26): ten tones, S1 Porcelain to S10 Ebony (the Virtual Villagers patcher's table and
look), plus Game's own (the game's own skin). All bare skin is toned, and of the baby art only the held baby. One file per
save, never a save field. Random tones for founders, arrivals and everybody already in a family when the setting is
first on; babies inherit by the Virtual Villagers rule. The picker is a Skin tone row in Villager Cheats > Change
Appearance; each change is an "Appearance changed" record. The masks ship as shape-only pictures.

The owner's decisions (2026-11-28):

1. **Look:** the recolour is the Virtual Villagers Fun Patcher's, number for number (its `vv_skin_tone_art.py`
   `shade` / `recolour` / `tone_scales` / `oklch_to_rgb` and `vv_skin_tones.py` `TONE_TABLE`): per row of cells, the
   2nd, 50th and 98th percentiles of the skin's OKLab lightness; SHADING 0.65, L_FLOOR 0.14, L_CEIL 0.985, GIVE 0.3,
   CHROMA_FLOOR 0.78, SHADOW_CHROMA 0.22. `patcher/vf1_skin_art.py` is the Python copy, `MakeRow` in vf1skin.cpp the C.
2. **Default:** off for players (everyone has the game's own skin); on in Select All Patches and Owner's Defaults.
3. **Preferred skin tone:** No preference (random tones, as before) or one of the ten; with one, 80 in 100
   (`Random(100) < 80`) of the randomly made family members get it and the other 20 one of the OTHER nine tones
   (never the chosen one), so exactly 4 in 5 have it: the Virtual Villagers patcher's rule. Babies always inherit.
   Shown right below the patch while it is ticked (VF1 has no per-patch settings window); written by Enable/Disable
   Patches to `settings.ini` `[SkinTones] PreferredTone=0..10` (`--skin-tone-preference` on the command line; not
   given: kept as it is).
4. **Description:** the owner's genetics note, word for word, in the patch's description.
5. **Preview:** the Skin Tones "?" and the Preferred skin tone "?" show a woman and a man standing, facing you
   (actions column 14, the head straight out: the Change Appearance standing look), in S1..S10, made at run time from
   the player's own game folder with the shipped masks (`vf1_skin_art.preview`); no game art is shipped. A sheet that
   is not the game's own (its SHA-256 differs from `SkinMasks/masks.json`) gives no preview, as the DLL then draws the
   game's own skin.

## What the player sees

- Every family member drawn in their tone: in the house (walking, every action, sitting), the Details, Adoption and
  marriage proposal portraits (the big heads and big bodies), a Random Event's picture, the Family Tree (the dead and
  those who left too) and the menu's background family. The baby a mother carries (carrying.png cell 3) is drawn in
  the baby's own tone. Hair, eyes, lips and clothes stay the game's own.
- Villager Cheats (with Cheat Upgrades on) > Change Appearance has a Skin tone row: Game's own (the game's own skin),
  S1 Porcelain ... S10 Ebony, and Reset to birth tone, for the picked villager or Everyone. Each change writes an
  "Appearance changed" record ("Old skin tone" / "New skin tone") to the Family History log when the log is on.

## Who gets which tone

| Who | Tone | Where in the code |
|---|---|---|
| A family with no tones file (the patch is new, or the file was lost) | everybody in the house and every Family Tree entry of every generation: a random tone, which is also their birth tone | `AfterLoad` -> `Reconcile(true)` |
| Founders, adopted children, spouses, visitors, Adoption and proposal candidates (real villager records in the house, so the portrait already shows the tone they arrive with) | random; with a Preferred skin tone, that tone about 4 times in 5 (the family's first load too) | `Newcomer`, `RandomTone` |
| A baby | rolled once, at the conception (CVillager::Impregnate spawns the babies hidden in theGameState +0x1B120/24/28): 95% `(father + mother) / 2 + rand(3) - 1` held to 1..10, 5% any tone; a parent with no tone (or Game's own) counts as the other parent; twins and triplets copy the first baby | `BabiesMade` (the conception call 0x48EBB2, chained) |
| vf1fun's Spawn Child (a child whose two parents are the current couple) | inherited, the same rule | `CoupleTones` |
| A copy the game makes of someone (the death behaviour's copy, Next Generation's adult heir) | theirs (one person: a change to either changes both) | `Newcomer`, `person` |

The random numbers are the DLL's own (xorshift32 seeded from the clock), never the game's rand(), so the game's own
events never shift. The father is the patriarch whose head and body the conception step passes (its name argument is
the constant "Joey"), as vf1logs.dll finds him.

## How it draws (section 2 of C:\vf1\skin-tone-runtime-design.md)

Each sheet of people is one SDL surface shared by everybody; every cell draw ends in BlitRectWithAlpha 0x404C30. While
a toned person is drawn, a blit from a sheet of people gets a kept copy of that one row of the sheet (one head, one
outfit) with the skin recoloured by the Virtual Villagers patcher's method (`MakeRow`: the row's skin colours counted
per pixel, sorted by lightness for the three percentiles, each colour shaded once; `skin_tables.h` from
tools/vf1_skin_tables.py, which reads `patcher/vf1_skin_art.py`), and the rectangle moves to the copy's row. At most 96 MB of copies are kept, least recently used first. The DLL reads each
sheet from the image table's grid (+0x2C), so it never loads a picture the game has not loaded.

Who is being drawn:

| Draw | Hook | The person |
|---|---|---|
| The house, the menu's family | DrawVillager 0x48B4D0, entry | the slot argument |
| The held baby | the carried-items draw 0x48A100, its two calls 0x48B7DE / 0x48B9F9 | the reserved baby slot's tone, only on carrying.png cell 3 |
| Details, Adoption, proposal | the portrait 0x486B60, entry | `this` |
| Random Event picture | 0x486D20, entry | `this` |
| Family Tree | the tree scene's three calls 0x439CC6 / 0x439E01 (DrawParent, the record in edi) and 0x439FA0 (DrawChild, record + k * 0xD8 in ebp) | the tree entry: its villager slot while the name and sex are theirs, else the person who holds that tree place |

The plain blit 0x404BC0 (the unscaled grid draws 0x4088B0 / 0x408920) is not reached by any of these: no direct call
path leads there (a call-graph walk from the five functions), and every emulated draw records that it is never entered.
theAlignVillagerScene also draws people but is a developer tool the game never opens (game state 5 is never set).

## The masks

`patcher/payload/SkinMasks/<sheet>.png`: 1-bit black and white pictures (white = skin), no game pixel, about 560 KB for
the 14 sheets, made by `tools/vf1_skin_masks.py` from the workbench's `layers\<sheet>\Skin mask.png`. carrying.png's
mask is cell 3 only (the tool refuses anything else). The DLL decodes them itself (its own inflate, CRC and Adler
checks) and uses a mask only when the game's sheet file is the very file it was made from (size and FNV-1a 64 in
`skin_masks.h`) and the picture is the sheet's size; any other sheet is drawn as the game draws it.

## The file

`<save folder>\Virtual Families 1 Patcher Data\Skin Tones\<save file>.dat`, the Children file's header (tag
`VF1SKIN`), up to 400 entries of 64 bytes: slot (-1 when not in the house), sex, the stored name, the tone (0 none,
1..10, 15 Game's own), the birth tone, head and body as last seen, two Family Tree places and a person number. Written
after theGameState::Save of every save file (temp file, then replace), rotated with the save; after a load, the file
naming the loaded save's FNV-1a 64 and size is used, else the backup's (slot + 20), else another save of the same
family's; an unreadable file is renamed `.unreadable-<k>.dat`, never deleted; a file another program holds is left as
it is and nothing is toned or written for that save in that session. Before a save only who is in the house or in
the tree is kept. Copy, Move and Delete Player Slot, Rename Family, Back Up Saves and Game Speed carry it and re-match
it (vf1_genealogy.sidecar_key / children_rekeys, vf1_copy_slot.slot_files, vf1_save.file_owner).

## For Revive (vf1revive.dll)

    int VF1Skin_ToneOf(int slot, int *birth);            // at the death: the tone (0 none, 1..10, 15) and *birth
    int VF1Skin_ToneGive(int slot, int tone, int birth); // after the revival, in the new slot: 1 when given

`GetModuleHandleW(L"vf1skin.dll")` + `GetProcAddress`; with Skin Tones off both give 0 and do nothing. ToneOf with
nothing held gives 0, and Give(slot, 0, ...) is refused: the revived villager is then a newcomer (a random tone).
Giving is not logged.

## Evidence

- `tools/vf1_skin_sites.py`: 16 pins on the vanilla exe, every hooked call's callers, the stolen bytes (whole, no
  branch, no eip), the tree registers never written between where they are set and the calls, the image table entries.
- `tests/test_skin_tone_draw.py` (Unicorn, the real DLL on the real exe, the shipped masks on the vanilla sheets):
  every hook site and the trampoline page made PAGE_EXECUTE_READWRITE; Default is the game's own draw byte for byte;
  a tone recolours exactly the skin of the head and body rows to `vf1_skin_art.py`'s colours (one level), alpha and
  every other pixel the game's own; all ten tones on the house's heads, bodies and actions and the portrait's big head
  and big body (60 rows); the older heads, actions, sitting, the portrait (big head, big body), the event
  picture, the Family Tree's parents and children, the held baby (cell 3 only, twins drawn twice); a modded sheet and
  a broken mask are drawn as the game draws them; the plain blit is never entered; a toned family picture; the
  preview picture. With `VVFP_SKIN_SRC` set to the Virtual Villagers patcher's `src` folder, `vf1_skin_art.py` is
  compared with its `vv_skin_tone_art.py` on real VF1 rows (the same pixels, 0 difference).
- `tests/test_skin_tones.py` (Revive's harness: the real Impregnate, ChangeName, SaveCurrentGame): first-load random
  tones kept across save and load; the Preferred skin tone (about 4 in 5 newcomers, babies still inherit, the setting
  held to 0..10); inheritance (60 conceptions, twins), a parent with no tone; arrivals and copies;
  renames; the tree, the dead and an earlier generation; Change Appearance, Reset to birth tone and the log record;
  Revive's two exports; the backup, a damaged file set aside, a shut file left alone, another family's file.
- `tests/test_family_history.py`: the "Appearance changed" record's lines.

## Not proven (needs the live game)

1. The real-PC time of a first draw of a row (a few ms expected) and of a sheet's first use (hashing the sheet file,
   decoding its mask: tens of ms for the walking sheets).
2. Real SDL: the row copies are SDL_CreateRGBSurface surfaces in the sheet's own format; proven on emulated surfaces.
3. The kept-row limit's freeing (96 MB): designed to free only between blits; not reached in the tests.
4. Two Family Tree people with the same name and sex in neighbouring generations who are NOT the same person and have
   the same head and body could share a tone (the heir rule).
5. The patcher's own pictures (Family Tree Maker, Picture Maker, the Clothing and Hairstyles page's previews) still
   show the game's own skin: a later step. The Skin Tones "?" preview is the one picture the patcher tones.
6. A first draw of a row now sorts the row's skin colours and shades each with the VV method (14-step searches): a
   little slower than before the first time a row is drawn in a tone; to be timed in the live game.
