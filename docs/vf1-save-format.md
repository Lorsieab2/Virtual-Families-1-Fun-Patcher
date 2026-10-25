# Virtual Families 1 save format (read by `patcher/vf1_save.py`)

Target: the vanilla `Virtual Families.exe` 1.01.00 (SHA-256 `5db828c3...4487`, image base 0x400000, no
ASLR). Addresses are VF1 virtual addresses.

**Standard.** A field is **VERIFIED** only when (a) the game's own save writer and loader were traced
(disassembled, and for the record layouts also emulated with unicorn in
`tests/test_vf1_save.py`) and (b) the value was checked against the owner's real saves (copies only).
Everything else is **UNCONFIRMED**; the reader still exposes those values, raw, under neutral names.
Real-save checks used every slot file copied from five save folders (VF1 vanilla, a 2023 copy, the modded
game, its backup and the release-test folder): 24-byte and 12-byte headers, versions 0x3F8 and 0x3F0,
generations 1 to 6, pregnancies, unborn babies, left-home children and old-age deaths.

## 1. Files

### 1.1 Where and what (VERIFIED)

| File | Belongs to | Written by | Evidence |
|---|---|---|---|
| `Documents\LDW\<exe name>\` | the folder | `ldwGameState::MakePath` 0x402FC0 | SHGetSpecialFolderPathA(CSIDL 5) + `\LDW\` + the running exe's file name without extension. A renamed exe gets its own folder. |
| `Virtual Families0.ldw` | **shared** (every slot) | theGameState::Save(0) 0x4237A1 | the options block: 0x88 bytes from theGameState+0x1B188 (current slot number at +0x1B188, the five slot-menu family names at +0x1B192/A7/BC/D1/E6, flags +0x1B1FB..FF). Saved first by every SaveCurrentGame and by Shutdown. |
| `Virtual Families<N>.ldw`, N = 1..5 | slot N | theGameState::Save(N) 0x423790 | the village: header + 0x1B180 bytes (section 2). |
| `Virtual Families<N+20>.ldw` (21..25) | slot N, backup 1 | the rotation below | |
| `Virtual Families<N+40>.ldw` (41..45) | slot N, backup 2 | the rotation below | |
| `ldwLog.txt` | **shared** | the engine log 0x40B8E8 | `MakePath("ldwLog.txt")`: in the save folder. Not per slot. |
| `ldw.ini` | **not in the save folder** | read only (GetConfigValue 0x402D60 / GetConfigPath 0x402D20) | GetModuleFileNameA's folder: the **game install folder**. Shared. Read for ForceFullScreen / ForceWindowed (0x424AA5). |

The file name prefix is the constant `"Virtual Families"` (theGameState::GetGameTitle 0x423740,
vtable slot 5, `mov eax,0x4B5E74`), formatted `"%s%d.ldw"` (0x4B273C) by MakeGameStatePath 0x4035F0. Only
the folder follows the exe name; the file names never do.

**The rotation.** `ldwGameState::Save(buf, size, n)` 0x403930, for n > 0: `DeleteFileA(path(n+20))`
(0x403960 -> 0x4038F0 -> 0x499182), `MoveFileA(path(n), path(n+20))` (0x403992 -> 0x49938D), then writes
`path(n)` (`"wb"`). `theGameState::SaveCurrentGame` 0x4238E0 saves `0`, then `slot`, then `slot+20`
(0x423910 `add eax,0x14`). So after an autosave / dialog save of slot N:

- `N` = this save, `N+20` = **the same data again**, `N+40` = the save before it.

`theGame::Shutdown` 0x422C10 (a clean quit) calls `Save(slot)` and `Save(0)` only, so after a quit:
`N` = the quit save, `N+20` = the save before it, `N+40` unchanged (older still).
Checked on the real folders: N and N+20 have identical payloads in most slots (an autosave was last)
and differ in the others (a quit was last); N+40, where present, always differs from N. Nothing ever writes N+60, and no other extension is written.

### 1.2 The patcher's own per-slot files (VERIFIED from the patcher's source)

| File | Belongs to | Source |
|---|---|---|
| `Virtual Families 1 Patcher Data\Slot <N>.ini`, N = 1..5 | slot N | `native/vf1fun/features.inc` SidecarPath / SaveVillageState: written after `theGameState::Save(slot)` only for `slot` 1..5, read after Load(1..5). **Never rotated**: there is no `Slot 21.ini` and no backup ini. |
| `Virtual Families 1 Patcher Data\Children\Virtual Families<n>.ldw.dat` | the slot of save number n (n = N, N+20 or N+40) | `native/vf1kids/vf1kids.cpp` SidecarPath: `<save folder>\Virtual Families 1 Patcher Data\Children\<save file name>.dat`. The DLL hooks theGameState::Save(slot) for every slot > 0, so SaveCurrentGame's `Save(N+20)` gives `...<N+20>.ldw.dat` too, and RotateSidecars moves a sidecar to `n+20` when the game rotates its save. |
| `...\Children\Virtual Families<n>.ldw.unreadable-<k>.dat` | the same slot | vf1kids MoveAside: a damaged or foreign sidecar set aside, never deleted. |

`vf1_save.file_owner(relative_path)` implements exactly this table.

### 1.3 Where the Back Up / Restore tool's rule (feat/tools-tab, `patcher/vf1_save_backup.py`) is wrong

- **21..25 and 41..45 are filed under slots 21..25 / 41..45**, not under slots 1..5. `_SLOT_LDW` takes the
  digits as the slot, so a one-slot restore of Save 3 leaves `Virtual Families23.ldw` and `...43.ldw` (and
  their `.ldw.dat` children sidecars) untouched, and `slots_in` lists "slots" 21, 41 ... for a backup.
- **`Virtual Families0.ldw` is filed as slot 0**: it is the shared options file (current slot and every
  slot's menu name), not a save slot; restoring one slot should not replace it, and it should not be
  listed as a save.
- **`...ldw.unreadable-<k>.dat`** (vf1kids' set-aside sidecars) matches neither pattern, so it is
  "unknown" instead of the slot it belongs to.
- `Slot N.ini` is right as far as the game and the patcher go (only N = 1..5 exist). `_SLOT_NAMED` also
  takes anything that starts with "Slot N" (e.g. "Slot 3 Achievements.ini"); VF1's patcher writes no such
  file.
- `ldw.ini` is not in the save folder at all (install folder), so it needs no rule there; `ldwLog.txt`
  as shared is right.

## 2. Slot file layout

### 2.1 Header (VERIFIED: ldwGameState::Save 0x4039C4 writes 24 bytes from 0x4E9228; Load 0x403760 reads both forms)

24-byte header (every save the 1.01.00 exe writes):

| Off | Type | Field | Evidence |
|---|---|---|---|
| 0 | char[4] | `ldwg` | Load checks `l`,`d`,`w`,`g` (0x4037CE..0x4037EC) |
| 4 | u32 | copied to 0x4E922C; UNCONFIRMED meaning (equal to the epoch's low dword in every real save) | 0x403826 |
| 8 | i64 | **epoch** (time_t): the base of `GetSecondsFromGameStart` 0x4036D0 = difftime(now, epoch) | 0x40382F/0x403839 |
| 0x10 | u32 | payload size, must equal the size asked for (0x1B180 for a slot, 0x88 for slot 0) | 0x4037F3 `cmp [esp+0x2C],edi`; 0x4039CD |
| 0x14 | u32 | copied to 0x4E923C; UNCONFIRMED (0 in every real save) | 0x403844 |

12-byte legacy header (older saves, still loaded): `ldwg`, u32 epoch (32-bit), u32 size
(0x40386A..0x4038D6: on a 24-byte mismatch Load seeks to 0, reads 12 bytes, checks magic and size at +8,
and uses +4 as the epoch's low dword with a zero high dword). 110 988-byte files in the owner's folders are
this form. The epoch is the same in every file of a folder (it is one global, 0x4E9230, rewritten by every
load and saved into every file).

**Payload.** `theGameState::Save` writes `theGameState+8`, 0x1B180 bytes (0x4238B9..0x4238CE);
`theGameState::Load(int)` 0x424A50 reads them (0x424B19) and memcpys them to `+8` (0x424B3F). So a field at
theGameState offset **G** is at **file offset = header size + G - 8**. Everything below is a theGameState
offset ("gs+"). The saved range is gs+0x8..gs+0x1B187; gs+0x1B188 (current slot) and beyond, including the
pending life-event list at gs+0x1B31C (0x423E2A) and the scene id gs+0x1B300, are **not** in a slot file.

### 2.2 Sections (VERIFIED: the `lea` before each SaveState call in 0x423790)

| gs+ | Size | Section |
|---|---|---|
| 0x298 | 0x4BC | CAchievement 0x412C50 (101 x 12) |
| 0x754 | 0x6B4 | CCollectableItem 0x413A40 |
| 0xE08 | 0xB4 | CDailyEmail 0x415DD0 (reset on load when version < 0x3F8, 0x424D7C) |
| **0xEBC** | 0xCB70 | **CFamilyTree** 0x481680: 30 records x 0x6C8 (section 2.5) |
| **0xDA2C** | 4 | **food** (CFoodStore 0x4221A0, int) |
| **0xDA30** | 0x34 | **CGameStats** 0x422230 (13 dwords) |
| **0xDA64** | 0x14 | **CGameTime** 0x4222C0 |
| 0xDA78 | 0x140 | CInventoryManager 0x496820 |
| **0xDBB8** | 8 | **CMoney** 0x422680: float money, u32 next interest time |
| 0xDBC0 | 0xC | CTech 0x422930 |
| 0xDBCC | 0x40 | CToolTray 0x496EE0 |
| 0xDC0C | 0x5E4 | CTutorialTip 0x44E0E0 |
| 0xE1F0 | 0x5A0 | CPetManager 0x4342D0 |
| **0xE790** | 0xC990 | **CVillagerManager** 0x489AC0: 30 x 0x6B8 (section 2.4) |

(Sizes other than those traced are the gaps between offsets.)

### 2.3 theGameState fields

| gs+ | Type | Field | Status | Evidence / real saves |
|---|---|---|---|---|
| 0x1B120/24/28 | int[3] | **unborn babies' villager slots**, -1 = none | VERIFIED | Init 0x42434A sets -1; Impregnate stores the baby slots, delivery 0x48C132 resets -1. Real: `(2,-1,-1)` with the mother pregnant and slot 2 an unborn (present 0, age 40) baby in the tree. |
| 0x1B12C | char[0x1C] | **family name** (the slot's name; the slot menu copies it, 0x42489D..) | VERIFIED | typed in theCreateNickNameDlg (0x41C72B `GetText(.., 0x14)`, max 20 chars), cleared by Init 0x42411C, kept by Restart 0x4243DE. Real: the owner's family names. Whether the game calls it a "surname" of each villager: UNCONFIRMED (villagers have only a first name, bio+0x10). |
| 0x1B148 | int | save version (0x3F8) | VERIFIED | set before each save 0x4238C4; real: 0x3F8, and 0x3F0 in old saves |
| 0x1B14C | u32 | Init: CGameTime::Seconds()+900 | UNCONFIRMED meaning | 0x424368 |
| 0x1B150 | u32 | baby cooldown (CGameTime seconds; Marry sets 1) | VERIFIED as written | 0x42437A, 0x4382CF; vf1fun 0x48EC70 |
| 0x1B154 | u32 | next marriage proposal (CGameTime seconds; 0 = none) | VERIFIED | 0x4451EF..0x44526C, 0x4385E6 |
| 0x1B158 | int | marriage proposals opened | VERIFIED | 0x445015 `+= 1` |
| 0x1B15C, 0x1B160, 0x1B164 | u32 | real-time (GetSecondsFromGameStart) timers; 0x1B164 = last UpdateAll | UNCONFIRMED (0x1B164 VERIFIED as written by UpdateAll) | 0x4243A3, 0x423CDF |
| 0x1B180 | int | **game speed**: 10 normal; >= 999 paused (Pause adds 999) | VERIFIED | 0x41E1CC, 0x41E21B; real: 10 and 1009 (paused) |
| 0x1B184 | byte | Reverse Day/Night | VERIFIED as written | 0x41E267 |
| 0x8..0x297 | | upgrades owned (gs+0xC+16k), repair progress, garbage (+0x188) ... | UNCONFIRMED here (see research/house_store.md) | |

### 2.4 Villager record (gs+0xE790 + slot x 0x6B8): CVillager::SaveState 0x485640 / LoadState 0x485720

The record index **is** the villager slot (+0x13538, the slot id the tree and life events use, is not
saved; CVillagerManager reset sets it to the index, 0x489820). VERIFIED by the save loop (0x489AC4..0x489B16:
record k <- villager k) and real saves (tree slot ids point at the matching record).

| Rec off | Villager off | Type | Field | Status | Evidence / real saves |
|---|---|---|---|---|---|
| 0 | +0x13574 | byte | **present** (in the game). Saved as 0 for a ghost (+0x13540) | VERIFIED | 0x4856DB..0x4856EE. Real: 0 for empty slots, unborn babies (also in gs+0x1B120), discarded marriage / next-generation candidates (0x4381AB, 0x436900), removed dead bodies, ghosts. |
| 1 | +0x13578 | byte | **left home** | VERIFIED | SetLeftHome 0x4857F0; 0x489E96: at age 380 (19 y) with no career -> leaves (ForgetPlans, SetLeftHome, life event 5). Real: 19- and 20-year-old children with career -1. Left-home villagers stay present, stop ageing (real: last_update frozen). The game's on-screen name for this (college?) is UNCONFIRMED: no reader of eTipCollege/eString_College* was traced. |
| 4 | +0x1357C | u32 | time left home, **CGameTime seconds** | VERIFIED | 0x4857FF..0x485804 |
| 8 | +0x2A34 | CVillagerBio (0xA0) | 0x489640 copies 0x28 dwords | VERIFIED | |
| 8 | bio+0 | int | **age in units** (1/20 year); years = units/20 | VERIFIED | Init 0x48520A, IncrementAge 0x4897F0, display 0x4852AC..0x4852B9 / 0x4384A0. Real: ages match. |
| 0xC | bio+4 | int | **sex**: 0 male, 1 female | VERIFIED | SetRandomName 0x48971D (1 -> female syllables); Init 0x4850BD. Real: names match. |
| 0x10 | bio+8 | int | random-name index (1..151) | VERIFIED as written | 0x4896FE |
| 0x14 | bio+0xC | int | voice (1..50) | VERIFIED as written | 0x48971D..0x489721 |
| 0x18 | bio+0x10 | char[0x1C] | **name** (game writes at most 0x19 incl. nul) | VERIFIED | 0x489741 (0x19), 0x4897B4; family-tree copies 0x481A01. |
| 0x34 | bio+0x2C | int | **head** sprite row 0..49 | VERIFIED | Init 0x485108..0x48516A |
| 0x38 | bio+0x30 | int | **body** sprite row 0..49 | VERIFIED | Init 0x48517D |
| 0x3C | bio+0x34 | char[26] | parent-1 name ("Joey" for every natural birth) | VERIFIED | Init 0x485226 strncpy 0x19; real: "Joey" |
| 0x56 | bio+0x4E | char[26] | parent-2 name (the mother) | VERIFIED | 0x485235; real: the mother's name |
| 0x70/74/78/7C | bio+0x68/6C/70/74 | int | parent-1 head / body, parent-2 head / body | VERIFIED as written (Init 0x485250..0x485266); no reader found | |
| 0x80 | bio+0x78 | int | conception argument (always 1) | UNCONFIRMED meaning | Impregnate 0x48653F |
| 0x84 | bio+0x7C | char[0x1C] | pending father's name | VERIFIED as written | 0x486551 |
| 0xA0/0xA4 | bio+0x98/0x9C | int | pending father's body / head | VERIFIED as written | 0x486559 / 0x48654B |
| 0xA8 | +0x2AD4 | CVillagerState (0x98) | 0x48F760 copies 0x26 dwords | VERIFIED | |
| 0xA8 | st+0 | int | real seconds banked for ageing | VERIFIED | 0x489DE9..0x489E32 |
| 0xAC | st+4 | u32 | **last ageing pass**, GetSecondsFromGameStart (real time = header epoch + value) | VERIFIED | Reset 0x48F7E4; real: decodes to the save's date |
| 0xB0 | st+8 | int | age units already processed | VERIFIED | Reset 0x48F7FD |
| 0xB4 | st+0xC | int | **health**; <= 0 = dead | VERIFIED | SetHealth 0x48F820, Reset 90; real: 0 for the dead |
| 0xB8 | st+0x10 | int | **death cause**, -1 alive | VERIFIED as stored; text map UNCONFIRMED | SetHealth stores the caller's cause; old-age roll passes 2 (0x48C068). Real: 2 for old-age deaths. Names for 0/1/3/4 follow the string ids 0x507..0x50C only. |
| 0xCC | st+0x24 | int | **pregnant**: age units at conception, 0 = not | VERIFIED | Impregnate 0x486535 (= st+8); delivery 0x48C073..; real: 541 with age 542 |
| 0xD0 | st+0x28 | int | babies carried 1..3 | VERIFIED | 0x486566/0x48659A/0x4865A6; real: 1 |
| 0xDC..0xF0 | st+0x34..0x48 | int[6] | six 1..100 stats (setters 0x48F8E0, 0x48F960, 0x48F9C0 [-500..500], 0x48FA20, 0x48FAC0, 0x48FB20) | UNCONFIRMED names (VF2 calls them energy, happiness, happiness trend, hunger, dirtiness, bladder) | no VF1 label reader traced |
| 0xF4 | st+0x4C | int | fertility 1..100 (twin/triplet bonus = max(0, value-85)) | VERIFIED role | Impregnate 0x486506..0x486523; Init rand(75)+15 |
| 0xF8 | st+0x50 | int | **"Wants kids?"** 1..99 | VERIFIED | text 0x48FCC0: value/10 -> 0x3D1 "No Way" .. 0x3D5 "Definitely" |
| 0xA8 other | | | the rest of CVillagerState | UNCONFIRMED | kept in `Villager.raw` |
| 0x140 | +0x2B6C | int | **career** id, -1 = none (children) | VERIFIED | SetNoCareer 0x48EFD0; reset 0x48EFF0 = rand(0x6C); real: -1 for every child |
| 0x144 | sk+4 | int | career level | VERIFIED as used | UpdateSalary 0x48F030 = table[career*8+level] |
| 0x148 | sk+8 | int | 10 at reset; UNCONFIRMED meaning | | 0x48F003 |
| 0x14C | sk+0xC | int | salary (from the table above) | VERIFIED as written | 0x48F016, 0x48F03F |
| 0x150 / 0x15C | +0x13620 / +0x1362C | int[3] each | likes / dislikes list | VERIFIED as saved; item meaning UNCONFIRMED | 0x485693..0x4856D5 |
| 0x168 | +0x2BA4 | 0x153 dwords | AI (SaveAI 0x485610, stride 0xC8 in memory) | UNCONFIRMED content | |
| 0x6B4 | | 4 | not written (padding) | VERIFIED | |

**Alive / dead / gone**: alive = present and health > 0 (VERIFIED). A dead body stays present with health
0 until 240 age units of real time pass, then present = 0 (0x489D31..0x489D8F, from research/time.md);
real saves show removed dead villagers with present 0, health 0 and cause 2 (VERIFIED). Old records are never cleared: an empty-looking slot may hold a stale
villager (present 0) and **slot numbers are reused**.

**Marriage / spouse.** There is **no spouse field** on a villager (VERIFIED: nothing in the record). The
couple is the current family record's parent-1 and parent-2 (section 2.5), whose `slot` fields point at the
villagers (only kept current in the current record: UpdatePeepRecord 0x4818F0 runs on the current record
only, 0x481960). `VF1Save.couple()` resolves them, checking slot + sex + head as FindPeepRecord 0x4817B0
does, plus the name. The game's own "matriarch / patriarch" (GetMatriarch 0x489950 / GetPatriarch
0x4899C0) is the first present, at-home, alive villager with a career of each sex: a rule, not a stored field.

### 2.5 Family tree (gs+0xEBC): CFamilyTree::SaveState 0x481680 / LoadState 0x481580

- SaveState copies the 30 records (0x1B2 dwords each) **but not the generation counter** (tree+0).
  LoadState resets the tree and copies records while their `used` byte is set, counting them: **the
  generation number = the number of leading used records** (VERIFIED, unrolled loop 0x4815A0..0x481668;
  real: 1..6). The current family is the last of them (GetCurrentFamily 0x481730).
- If the count is 0 after loading, Load starts a tree (StartFamilyTree 0x481E00) from the villager that
  0x48A490(1) returns (0x424D97..0x424DCC; that function's rule is UNCONFIRMED).

Family record (0x6C8): VERIFIED from UpdateParents 0x4819C0, AddOffspring 0x481AA0, StartNextGeneration
0x481B30, ReportDeath 0x481CF0 and real saves.

| Off | Type | Field |
|---|---|---|
| 0 | byte | used |
| 1 | byte | a parent died and children survive ("Next Generation" offered, 0x481780; real: 1 when both parents were dead) |
| 2 | byte | notify next generation (0x481790/0x4817A0) |
| 4 | SPeepRecord | parent 1 (the heir / founder; StartNextGeneration writes it) |
| 0xDC | SPeepRecord | parent 2 (the one who married in; UpdateParents writes the newcomer here when parent 1 is used) |
| 0x1B4 | int | child count 0..6 |
| 0x1B8 | SPeepRecord[6] | children in order of AddOffspring (birth, or adoption) |

SPeepRecord (0xD8):

| Off | Type | Field | Status |
|---|---|---|---|
| 0 | char[26] | name (copied with n = 0x19) | VERIFIED |
| 0x1A | byte | used | VERIFIED |
| 0x1C | int | sex | VERIFIED |
| 0x20 / 0x24 | int | head / body (copied when the person joins) | VERIFIED |
| 0x28 | int | villager slot; -1 = dead / gone (ReportDeath) | VERIFIED; **stale in older records** (real: earlier generations' children point at slots since reused) |
| 0x2C | int | parent 1 only: index of this person in the previous record's children, -1 = founder (StartNextGeneration 0x481B60..0x481BF6). Parent 2 and children: never written (0 from the reset memset) | VERIFIED (real: the heir's index; 0 for every parent 2) |
| 0x30 | int | career (UpdatePeepRecord) | VERIFIED |
| 0x34 / 0x5D | char[0x29] | likes / dislikes text (UpdatePeepRecord, n = 0x28) | VERIFIED |
| 0x86.. | | unused by the traced writers | UNCONFIRMED |

Generation links: record g+1's parent 1 is child number `parent_child_index` of record g. A child adopted
through The Little Visitor or the patcher's Adopt Outside Child is a child entry with no parents in its bio
(empty parent names); a spawned child (the patcher's Spawn Child) has the couple's names in its bio. Children 7..28 of
the patcher's Up to 28 Children are not in the save (Children sidecar, section 1.2; not parsed here).

### 2.6 Time (VERIFIED)

- **CGameTime** (gs+0xDA64): +0 speed, +4 previous speed, +8 GetSecondsFromGameStart of the last speed
  change, +0xC game seconds banked then, +0x10 GetSecondsFromGameStart at saving (SaveState 0x4222C0;
  LoadState 0x4223F0 uses `now - [+0x10]` as the time away). `Seconds()` 0x422320 =
  `banked + (now - changed) / (speed/10)`; `GameTime.seconds_at_save()` applies it at `+0x10`.
- Real time of any GetSecondsFromGameStart stamp = header epoch + stamp (0x4036D0). Real: the save stamps
  decode to the dates the saves were made.
- **CGameStats** (gs+0xDA30): +0 village start stamp (CStoryScene::Activate 0x43A7F1), +8 babies born
  (0x48678D), +0x18 maximum population (0x424FB6), +0x20 oldest age ever in years (0x489F07). Other dwords
  UNCONFIRMED (+4 = 99 at reset, 0x4221FD).
- Ageing: one age unit per `60 x speed` real seconds while running (0x489E78..0x489E86; 600 s at speed 10);
  catch-up after time away is capped (86 400 s over 24 h, otherwise about 31 000 s; 0x489DF5..0x489E32).
- Money: float at gs+0xDBB8, next interest at +0xDBBC in CGameTime seconds (0x422830). Food: int gs+0xDA2C.

## 3. What the save does NOT hold (VERIFIED by range)

No life-event history: the pending life events (1 wedding, 2 conception, 4 death, 5 left home;
QueueLifeEventPending 0x423E10) live at gs+0x1B31C, outside the saved range. No marriage date, no birth
date (only age), no death date (only last_update of the body), no divorce or eviction marker (VF1 has no
native divorce or evict). A log must therefore be written by the DLL as things happen (section 4).

## 4. Hooks a log DLL needs

The sites below are calls or vtable entries. The save-side facts above were traced for this document;
the in-game behaviour at each site (delivery, the death behaviour, the body timer, the Marry handler)
comes from `research/villagers.md` / `research/time.md`. **Since re-traced for vf1logs.dll** (Family Logs):
see docs/FAMILY_LOGS.md for the sites actually hooked (the delivery is seen at the physiology pass's only
call, 0x424F93; the cause is read at ReportDeath instead of hooking SetHealth), proved by
tools/vf1_logs_sites.py and emulated in tests/test_family_logs.py; not yet run live.

| Event | Hook | What is known there |
|---|---|---|
| Birth (conception creates the baby) | `CVillager::Impregnate` 0x4864D0 (call site 0x48EBB2) / AddOffspring 0x481AA0 | babies spawned at conception (present 0), slots in gs+0x1B120..28; actual **birth** = delivery in the mother's per-unit update 0x48C073..0x48C2FD (present set 1). Log the conception at Impregnate and the birth at delivery. |
| Death | `CFamilyTree::ReportDeath` 0x481CF0 (callers 0x48E200 death behaviour end, 0x489D8F body removal) and SetHealth 0x48F820 (cause) | health 0 and cause at SetHealth time; ReportDeath also runs for the body removal, so log once per villager. |
| Marriage | `CFamilyTree::UpdateParents` 0x4819C0 (call 0x438337; vf1fun's same-sex path calls it too) | both villagers; the candidate's dowry at scene+8 |
| Next generation | `CFamilyTree::StartNextGeneration` 0x481B30 (0x4368E6; also via StartFamilyTree 0x481E00 for generation 1) | after a true return tree+0 is the new generation |
| Adoption (new family / new person) | CAdoptionScene::HandleMessage 0x436780 (StartFamilyTree 0x4368C5) | |
| Adoption (outside child) | AddOffspring 0x481AA0 with an empty parent bio, from CEventTheLittleVisitor ImpactGame 0x418800/0x4188B0 or vf1fun AdoptOutsideChild | |
| Left home (college / Boarding School) | `SetLeftHome` 0x4857F0 (call 0x489EC5) | at age 380 with no career; the save keeps the left-home time |
| Divorce / eviction | vf1fun's own DivorceSpouse / OpenNewFamilyAdoption (family.inc) | no native event; the DLL must log them itself |
| After save / after load | theGameState vtable Save 0x4B5E6C / Load 0x4B5E68 | Load runs for slots 1..5 at start-up; the last successful load is the village played |
