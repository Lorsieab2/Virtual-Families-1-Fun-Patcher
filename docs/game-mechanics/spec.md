# Virtual Families 1: "Game Mechanics" window spec (read-only research), v1

Target: the vanilla `Virtual Families.exe` 1.01.00 (SHA-256 `5DB828C3...ECA4487`, the vanilla hash in
`docs/vf1-save-format.md`), analysed from a copy. Every address is a VF1 virtual address (image base 0x400000, no
ASLR). Layout and section numbers follow the VF2 patcher's Game Mechanics spec so the two line up; every fact was
re-traced in VF1's own exe, and no VF2 number was copied. Where VF1 differs from VF2 the row says so.

Inputs read: the VF1 static RE notes `time.md`, `villagers.md`, `house_store.md` (kept outside the repo; the VF1 repo
has no `discoveries.md` on any branch); `docs/vf1-save-format.md` (origin/feat/save-reader); the VV1 spec and
clamp_verify method. Nothing in any repo, save or install was changed; no game was launched; nothing was pushed.

## Evidence labels

- **VERIFIED-E**: the routine was run as linked inside unicorn (`vf1emu.py`) with the inputs the game supplies, and
  the odds were counted over every value of the roll. `GetRandom(N)` 0x403650 is `rand() % N` (CRT rand
  0x498BD8, MSVC LCG). Over the LCG's full period every 15-bit value 0..32767 appears equally often, so each forced
  result v is weighted by #{r < 32768 : r % N = v} / 32768. These are the game's exact odds; "rand(100) < 30" is
  30.03%, not 30%.
- **VERIFIED-C**: the routine sits on a traced call path (section 0) and the rule is the instruction sequence itself
  (constants, compares, one roll), read in VF1's disassembly.
- **UNCONFIRMED**: not on a traced path, reached only from player input that was not traced, a meaning the code does
  not show, or a patcher DLL behaviour read from its source but not run. Stated as such.
- Nothing is inferred from save values alone. No design choice is called a bug.
- **The game with the patcher** (section 22): the same three labels. The patcher's own `vf1fun.dll` (and, for Up to
  28 Children, `vf1kids.dll`), built from `native/` exactly as `native/build.bat` / `build_kids.bat` build them, is
  mapped beside the vanilla exe in the same harness (`dllemu.py`). Its own `VF1Fun_Startup` runs first with the
  manifest defaults (settings.ini answered from `manifest.json`), so every byte patch, jump, retargeted call and
  vtable slot it installs is in the emulated image as it writes it; then the game's routine (or the DLL's
  per-frame `VF1Fun_Tick`) runs with the inputs the game supplies. Only Windows itself is answered by stubs
  (VirtualProtect, the settings file, message boxes, the isolation-aware dialog and LoadLibrary wrappers).
- `GetRandom(N)` for **N > 32,767** takes another path (0x403671): **floor(rand() x (N - 1) / 32,767)**, 0 when
  rand() is 0 (the doubles 32,767.0 at 0x4B2748 and 2^32 at 0x4B2750; emulated for all 32,768 raw values,
  `t_getrandom.py`: monotone, every value distinct). The Mortality Curve's `GetRandom(1000000)` uses it, so its odds
  are weighted through that path, not as rand() % N.

**Speeds.** VF1's speed value (theGameState+0x1B180) is a divisor: one age unit takes 60 x speed real seconds, and
CGameTime game seconds run at 10/speed of real time (`CGameTime::Seconds` 0x422320). Stock VF1 only ever writes 10;
the patcher's Time Controls adds **Slow 20, Normal 10, Fast 5** (and 5x = 2, 10x = 1). Real times below are written
**Slow / Normal / Fast**. Paused = speed + 999.

## 0. Reachability (traced, `reach.py`)

Recursive descent from the PE entry with vtables made live when reached code stores them (the VV1 method), plus the
CRT static-initializer tables (`_initterm` 0x4B2464..0x4B2540 and 0x4B2544..0x4B2560, pushed by the CRT at
0x4989B2..0x4989DA); without them the behaviour table (below) was missed.

- **Frame loop**: entry 0x49BCD2 -> CRT start -> `WinMain` 0x425240 (call at 0x49BC64) builds theGame (vtable
  0x4B5E04, 0x4252DB) and calls vtable +0x18 = `ldwGame::Run` 0x402CC0 (0x4252FA). Run calls vtable +0x1C =
  `theGame::GameUpdate` 0x422D90 every frame (0x402CD7). GameUpdate case 0 gets the main scene (0x444D30) and calls
  its vtable +0x10 = 0x40C460 (0x422E0D), which calls vtable +0x20 = `theMainScene::UpdateScene` **0x444DB0**
  (0x40C471) while the house screen is active.
- **Frame rate**: theGameState vtable +0x28 = 0x402FA0 returns **30**. How the window uses it was not traced, so
  "per frame" rolls are given per frame and converted at 30 fps as an upper bound. VERIFIED-C (getter only).
- **Inside UpdateScene** (VERIFIED-C):
  - **2-second step** (0x444E28..0x444EE0: `ldwEventManager::GetSeconds() >= scene+0x30`, then +0x30 = now + 2):
    `theRealtimeManager::UpdateAll` **0x424F80** (0x444E9A) -> `AllVillagersTimeflowUpkeep` **0x489D00** (0x424F89)
    and `AllVillagersRealtimePhysiologyAndProductivityUpkeep` **0x48BC90** (0x424F93), then max population and the
    game-over tip; then the house-malfunction roll (0x444ECD). This step reads no pause flag.
  - Per frame: the island-event timer (0x445271), the marriage e-mail timer (0x4451EF), `CCollectableItem::Update`
    0x414BF0 (collectibles and messes), villager plans (0x489CC0 -> 0x486F20 -> 0x489540 -> 0x48E350).
- **Behaviour table**: the initializer 0x480260 registers **316** behaviour functions (306 through 0x452470, 10 through 0x452490; code 0x452420..0x480260; see section 24) into
  the table object 0x5AAA38 (`behaviours.py`). They hold 4,492 of the 5,087 roll sites (section 18).
- Store, drag-and-drop and dialog handlers are player input; their dispatch through the framework was not traced, so
  rules that run only there are marked.

## 1. Clock, speed, pause, time away

| Item | Rule | Real time | Save (file offset) | Status |
|---|---|---|---|---|
| Speed | gs+0x1B180. Stock writes only 10 (Options "No" 0x41E21B, Space 0x440CB2, theChangePlayerDlg 0x41C169, theCreateNickNameDlg 0x41C701). Patcher Time Controls writes 20 / 10 / 5 (/ 2 / 1), each through `SetSpeed` (vf1fun.dll 0x10008B02..0x10008BB5, wanted speed 0x10034048), and always saves 10 (paused stays paused: 1009); its Load wrapper turns any other value into 10 / 1009 (Save 0x10003CA0, Load 0x10003B80) | | 0x1B190 | VERIFIED-C (stock writers; patcher behaviour in the v1.1 vf1fun.dll bytes and `features.inc`) |
| Pause | Options "Yes" 0x41E1CC: `SetSpeed(999)` and **gs+0x1B180 += 999** (add, not set). Space: paused -> speed - 999 (0 becomes 10); else pause. Options "No" sets 10 | | | VERIFIED-C |
| Game seconds | `CGameTime::Seconds` 0x422320 = banked + (real s since the last speed change) / (speed/10). Paused, it is frozen: `SetSpeed(999)` stores speed 0 (`xor ebp, ebp` 0x42246F, stored 0x422574) and `Seconds` returns the banked value when the multiplier is 0 (0x42233C); real paused saves hold clock speed 0 | 1 game s = 2 / 1 / 0.5 real s | CGameTime 0xDA74 | VERIFIED-C |
| Real seconds | `GetSecondsFromGameStart` 0x4036D0 = now - header epoch; keeps running while the game is closed | | header +8 (i64) | VERIFIED-C |
| Game seconds while closed | `CGameTime` save 0x4222C0 writes speed, previous, mark (+0x28), banked (+0x2C) and the real now; the load 0x4223F0 (from 0x424B53) restores the mark unchanged, so `Seconds` counts the closed time at the saved speed (always 10: stock has no other, the patcher's `NormalSpeedForSaveFile` sets 10 before a save), with no cap; a clock saved paused (speed 0) stays frozen. The timer list `SetSpeed` rescales has its count at 0x50C5C8, which no instruction writes by address | 1 game s = 1 real s while closed | CGameTime 0xDA74 | VERIFIED-C (2026-10-27) |
| Age unit | `AllVillagersTimeflowUpkeep` 0x489D00 adds real s since the villager's stamp to a bank, ages bank / 60 / speed units, keeps the remainder | **1 unit = 20 / 10 / 5 min; 1 year (20 units) = 6 h 40 m / 3 h 20 m / 1 h 40 m** | rec +0xA8 bank, +0xAC stamp | VERIFIED-E (`t_timeflow.py`: 1200 / 600 / 300 s give 1 unit; 1 s less gives 0) |
| Catch-up cap | bank > 86,400 -> **86,400** and the speed rule is skipped; otherwise speed 5: > 38,200 -> 31,000; speed 20: > 23,800 -> 31,000; speed 10 and any other value: > 31,000 -> 31,000 | see table below | | VERIFIED-E |
| While paused | speed >= 999: bank set to 0 every step: **no aging, and the paused time is never credited** | | | VERIFIED-E (1005 / 1009 / 1020: 0 units after 3 days) |
| A villager with stamp 0 | skipped (never ages) | | | VERIFIED-E |
| Day / night | `CNight::GetTimeOfDay` 0x4912C0 = **PC local clock** hour + min/60 + CNight+0x680 (always 0), +12 h with Reverse Day/Night (gs+0x1B184) | follows the PC clock | 0x1B194 | VERIFIED-C |
| Patcher: Time Warp | Cheat Upgrades (on by default), Time Controls page: moves the saved start (0x4E9230) back 3,660 x speed s and CGameTime by 36,600 game s, runs `AllVillagersTimeflowUpkeep` with the per-speed catch-up cap jumped over (0x489E08 -> 0x489E3C) and the realtime update 0x424F80; money above (money before + $750) is cut back. Emulated (`t_warp.py`): **61 units** at Normal, also while paused (speed 1009 restored after); salary 10,000 gains exactly +$750, salary 48 +$126 | | | VERIFIED-E |

**Time away, emulated** (`t_timeflow.py`, `out_clamp.txt`; credited = units x 60 x speed + bank). This settles the
two readings: **reading B is what the code does.**

| Bank (s away) | Slow (20) | Normal (10) | Fast (5) |
|---|---|---|---|
| 23,800 (6 h 36 m 40 s) | 23,800 s, 19 u | 23,800 s, 39 u | 23,800 s, 79 u |
| 23,801 | **31,000 s, 25 u** | 23,801 s, 39 u | 23,801 s, 79 u |
| 30,000 | 31,000 s, 25 u | 30,000 s, 50 u | 30,000 s, 100 u |
| 31,001 | 31,000 s, 25 u | 31,000 s, 51 u | 31,001 s, 103 u |
| 38,201 | 31,000 s, 25 u | 31,000 s, 51 u | **31,000 s, 103 u** |
| 50,000 | 31,000 s, 25 u | 31,000 s, 51 u | 31,000 s, 103 u |
| 86,400 (exactly 24 h) | 31,000 s, 25 u | 31,000 s, 51 u | 31,000 s, 103 u |
| 86,401 and more (200,000) | **86,400 s, 72 u (3.6 y)** | **86,400 s, 144 u (7.2 y)** | **86,400 s, 288 u (14.4 y)** |

So: up to 6 h 36 m 40 s / 8 h 36 m 40 s / 10 h 36 m 40 s counts in full; from there to exactly 24 h counts as
8 h 36 m 40 s (on Slow that is *more* than the time away between 6 h 37 m and 8 h 37 m); more than 24 h counts as
24 h. The bank also carries the remainder from the last pass (< 60 x speed s). VF1 differs from the VF2 spec, which
reports a single 31,000 s cap.

## 2. Per-unit villager upkeep (the core of every need)

`AllVillagersRealtimePhysiologyAndProductivityUpkeep` 0x48BC90, from the 2-second step. For every present,
at-home villager with health > 0 it processes each unit n from processed age (rec +0xB0) up to the age, one at a
time, repeating passes until nobody is behind, so a catch-up replays every credited unit in one frame. Status
VERIFIED-E (`t_phys.py`, `t_life.py`, `out_life.txt`, `out_life2.txt`) unless marked.

| Every | Rule | Address |
|---|---|---|
| 4 units (80 / 40 / 20 min) | Hunger +5 (`0x48FD30`; above 80 the gain is halved to +2) | 0x48BD21 |
| 3 units (60 / 30 / 15 min) | Health state, happiness state, sickness check (below) | 0x48BD49..0x48BD5E |
| even units, only the last 12 units of a catch-up | Energy state (below; reads the PC clock) | 0x48BD8A (VERIFIED-C) |
| 3 units | **Salary**: money + salary x 3 / 24 = **salary / 8**, paid whatever the career field holds (a careerless villager with a non-zero salary field is paid) | 0x48BDD4 |
| unit | Poo (rec +0xF0) >= 90: set to 25..49 (25 + rand(25)) | 0x48BDF6 |
| unit | **Eating**: food > 0 and (food > 50, or a 50.05% roll when food <= 50): if hunger > 50, food -3 and hunger -3. Otherwise (no food, or the missed roll): 30.03% chance of health -1 (cause 1) | 0x48BDFB..0x48BE55 |
| unit | **Waste**: food >= 1,000 and hunger > 50: 76.05% chance of 3 more food used | 0x48BE5A |
| unit | **No food** (food <= 0): health -1 (cause 1) with 76.05%, or **always** when the villager's name index (rec +0x10) is a multiple of 6; then, at health <= 20 with an odd name index not a multiple of 6, a 31.03% chance of +1 | 0x48BE8A..0x48BF22 |
| unit | **Sick**: 61.06% chance of health -1 (cause 0); at health <= 20 it also needs a 31.03% roll (18.95% in all) | 0x48BF27 |
| unit | **Recovery** (food > 0, not sick): 50.05% chance of +1 health; at age 55+ (`IsNotOld` 0x4897E0 false, age >= 1,100 units) 50.05% x 20.02% = 10.02% | 0x48BF6A |
| birthday unit (n % 20 = 0) | **Old age** (section 4) | 0x48BFC6 |
| unit | **Birth** when pregnant (section 6) | 0x48C073 |
| unit, catch-up only (more than 2 units behind), adult with a career, not sick, not pregnant | `0x488F80` unwatched work (section 7) | 0x48C307 |
| unit | Age 700 / 900 / 1,000 / 1,200 / 1,300 units advance achievements 0x5D..0x61 | 0x48C391 |

**Health limits** (`AdjustHealth` 0x48F860, VERIFIED-E): a loss below 15 health and a gain above 90 are halved
(C truncation), and a +1 above 90 is zeroed outright. So **-1 losses never take health below 14**, and **+1 recovery
never takes health above 91** (health 95: 0% recovery). Starvation (cause 1) and disease (cause 0) only ever pass
-1, so they cannot kill on their own; health reaches 0 through the health-state step (-5..-2 below 15 becomes -2..-1,
cause -1 "Unknown") or event damage. `SetHealth` stores the cause only when health <= 0; otherwise cause = -1.

Record offsets (file = 0xE7A0 + slot x 0x6B8 + offset; section 19): energy +0xDC, happiness +0xE0, happiness trend
+0xE4, hunger +0xE8, dirtiness +0xEC, poo +0xF0. Info-panel labels: the panel sets bar 0xA from happiness, 0xB from
100 - hunger ("Fed"), 0xC from energy and 8 from health (0x44B927..0x44B976); the label strings Happiness 0x2F, Fed
0x31, Energy 0x32 and Health 0x431 are created at 0x44B307..0x44B499. Which bar each label sits beside: UNCONFIRMED
(layout not traced).

### Health state (every 3 units, `UpdateHealthState` 0x48FE80) VERIFIED-C
Delta = 0; -1 if happiness <= 10; -1 if hunger >= 90; another -1 if hunger >= 100; -1 if exactly 1 food group is
active; +1 if exactly 4 are active (5 counts as neither); if sick: -1 with 15.01% (symptoms only) or 40.04% (with an
infection). Clamped to -5..+5, applied with cause -1 through the health limits above.

### Energy (`0x490570`) VERIFIED-C
Delta: -4 if energy >= 10 and the PC clock is >= 20:00 or < 05:00; +8 if energy <= 70 and the clock is
05:06..17:00; -1 each for happiness <= 10, health <= 25, health <= 10, hunger >= 90; -3 if sick; clamped -6..+10;
applied by `AdjustEnergy` 0x48F910 (halved when falling below 10 or rising above 80; energy kept 1..100).

### Happiness (every 3 units, `0x48FF30`) VERIFIED-C
A trend (rec +0xE4, -500..500) collects: happiness < 25: +100 / > 85: -100; food groups: 10 x groups - 20;
`UpdateInterest`, then money < 1,000: -30, < 100: another -75, > 8,000: +35; food <= 250: -100, <= 50: another -100;
sick: -150; mess (socks + weeds + wrappers + smudges): >= 10: -40, >= 20: another -40, 0: +50, 1..4: +25;
**+10 per owned house upgrade** (15 flags gs+0x2C..0x10C); like-specific bonuses for owned upgrades (+10..+45 per
match); for each liked career room (likes 0x27 / 0x51 / 0x50), 500 x (room level - 1); the head couple's own career
level x 10 (everyone else +50); population 1: -75, else 40 x population - 60; for the couple, 30 x (2 - |desire
difference / 20|); hunger >= 90: -100; health <= 10: -100. Then happiness += clamp(trend/100, -5, +5) (-2 instead
of a gain when food <= 5 or sick; halved below 20 / above 80) and the trend is halved.

### Food groups (nutrition) VERIFIED-E
Four groups: Grains, Dairy, Meats, Fruits and Veggies (item short names 4..7 / 8..11). Putting a bag in the kitchen
(0x446DEC..0x446E70, player drop) runs `0x48A680(group, organic)`: every present, at-home, living villager gets that
group until **real time + 86,400 s (24 real hours, any speed)**; organics also add trend +5..+14 and happiness
+0..2. Food: groceries +150, organics +250. `FoodGroupsActive` 0x48FE30 loops over **five** slots: the fifth flag
is the low byte of group 1's expiry and its expiry is the career id. Emulated (`t_groups.py`): a **careerless**
villager with N >= 1 groups counts **N + 1**; an employed villager counts N, and each call clears that low byte
(group 1 then ends up to 255 s earlier). Code as built (see section 20).

## 3. Sickness and symptoms (every 3 units, `UpdateDisease` 0x490640) VERIFIED-E

Seven symptoms (rec +0x104..+0x10A, expiries +0x10C..) and two infections, mild (rec +0x128) and serious (+0x129).
Symptom names and the medicine for each: UNCONFIRMED (the store sells Throat Lozenges, Peptic Syrup,
Anti-inflammatory Pill, Antitussive Syrup, Cortisone Cream, Antihistamine, Penicillin, Vancomycin; the mapping was
not traced).

- Healthy villager, per check: rand(1000) < base, base 10, **25 when anyone at home has a symptom** (`0x48B1F0`;
  that villager's first symptom is passed on), -2 with exactly 3 food groups, -5 with a count of 5. If hit:
  rand(100) < 3 serious infection, < 10 mild infection, else one symptom.

| Case | Any | Symptom | Mild | Serious |
|---|---|---|---|---|
| employed, 0 or 4 groups | 1.007% | 0.906% | 0.071% | 0.030% |
| employed, 3 groups | 0.806% | 0.725% | 0.056% | 0.024% |
| careerless, 4 groups (counted as 5) | 0.504% | 0.453% | 0.035% | 0.015% |
| a sick housemate | 2.518% | 2.266% | 0.176% | 0.076% |

  Every 60 / 30 / 15 real minutes.
- A symptom lasts until **real time + 6..17 h** (`0x48FD80`: (rand(12) + 6) x 3,600 s; emulated 21,600..61,200 s,
  any speed); a symptoms-only villager loses its first symptom when that time passes (`0x48FDC0`).
- Mild infection: 50.05% chance to add a random symptom when it has none; ends with rand(100) < 3 (3.00%).
- Serious infection: 50.05% chance to add a new symptom while it has fewer than 2; ends with rand(250) < 3 (1.21%).
- Effects of being sick: section 2 (61% health loss per unit, no recovery, trend -150, energy -3, unwatched work / 8,
  health-state roll).
- Medicines, the Doctor Consultation and Baby Boost are player actions: UNCONFIRMED.

## 4. Death

| Cause | Rule | Status |
|---|---|---|
| Old age | Birthday units only (n % 20 = 0). Threshold T = 1,100 + 20 x food groups counted + 20 Air Purifier (gs+0x4C) + 20 Bathroom Upgrade (gs+0x8C) + 60 if health > 90. If n > T: death chance = 10% x (years - T/20), SetHealth(0, cause 2). | VERIFIED-E (`t_life.py`, `t_groups.py`) |
| Old age, patcher | Older Villager Mortality Curve (on by default): a jump at 0x48BFC6 (`mov ecx,ebx; call 0x48FE30`) runs `FoodGroupsActive` and then the DLL's `VF1RollMortality(unit, groups)`, which ends at the stock block's end 0x48C073: birthdays only; effective age = years - min(groups, 4); hazard = 1 - exp(-(0.00365 x years past 55 + 0.06 x years past 110)) in millionths (capped 999,999); death (SetHealth(0, cause 2)) if `GetRandom(1000000)` < hazard. Air Purifier, Bathroom Upgrade and health > 90 no longer count. Emulated in the full upkeep (`t_oldage2.py`: the threshold found by bisection on the forced roll and both sides re-run, odds through the large-range GetRandom): 0 groups **0.37% at 56, 3.59% at 65, 7.04% at 75, 15.15% at 100, 18.19% at 110, 23.23% at 111, 56.71% at 120, 77.09% at 130, 93.59% at 150, 99.73% at 200**; 4 groups the same 4 years later; careerless 4 groups = 4 groups; upgrades and health 95 = no upgrades; from effective 317 every roll except raw rand 32,767 dies (1 in 32,768 survives) | VERIFIED-E |
| Disease, starvation | -1 steps stop at 14 health (section 2), so they lower health but cannot reach 0 by themselves | VERIFIED-E |
| Unknown (-1) | the health-state step or other damage reaching 0 | VERIFIED-C |
| Work accident (3), Act of Nature (4) | no VF1 call site passes them | VERIFIED-C (absence in the AdjustHealth / SetHealth callers listed in time.md) |
| Body removal | a dead villager stays present until **240 units of real time** after its last upkeep stamp, then `ReportDeath` 0x481CF0 and present = 0 (0x489D31..0x489D8F): **80 h / 40 h / 20 h** (emulated at 239 / 240). The death behaviour's own end (0x48E1D4) usually removes it first: UNCONFIRMED timing | VERIFIED-E (timer) |

Old-age table (employed villager, health <= 90, no upgrades; % per birthday):

| Food groups | 10% at | 50% at | 100% at |
|---|---|---|---|
| 0 | 56 | 60 | 65 |
| 1 | 57 | 61 | 66 |
| 2 | 58 | 62 | 67 |
| 3 | 59 | 63 | 68 |
| 4 | 60 | 64 | 69 |

Each extra +20 (Air Purifier, Bathroom Upgrade, health 91) moves the table one year later. Best case (careerless,
4 groups counted as 5, both upgrades, health 91): 10% at 66 ... 100% at 75. **No villager can live past 75** in stock
VF1. A birthday that falls inside a catch-up is rolled like any other.

Cause names (string ids 0x507 + cause + 1): -1 Unknown causes, 0 Disease, 1 Starvation, 2 Old age, 3 Work accident,
4 Act of Nature; the code that picks the string was not found: UNCONFIRMED. Save: rec +0xB4 health, +0xB8 cause.

## 5. Aging and life stages

| Stage | Age units (years) | Source | Status |
|---|---|---|---|
| Newborn | created at 40 units (2 y) | `Impregnate` passes 0x28 to the spawner (0x48661E) | VERIFIED-C |
| Child / adult split | 280 (14) | adult count 0x48ACD0, interactions 0x4410C9 | VERIFIED-C |
| No career at creation | age/20 <= 16 (< 340) | `CVillager::Init` 0x4852C3 | VERIFIED-C |
| Adult-adult interactions | 360 (18) | 0x441142 | VERIFIED-C |
| Leaves home | crossing 380 (19) with no career | section 9 | VERIFIED-E |
| Older head sprites | 900 (45) | 0x48B5AE | VERIFIED-C |
| Old (`IsNotOld` false) | 1,100 (55) | 0x4897E0 | VERIFIED-E |
| Maximum | none in code; old age ends every life by 75 | section 4 | VERIFIED-E |

Oldest-ever statistic GameStats+0x20 (file 0xDA60) in years (0x489EE4, VERIFIED-E). Children are drawn scaled by
(age/14 + 80)% below 280 units (0x48B5FF, VERIFIED-C).

## 6. Pregnancy and birth

- **Who**: only the Matriarch (first present, at-home, living woman with a career) with the Patriarch. Plan step 0x41
  in `ProcessCurrentPlan` 0x48E350 (0x48EB33..0x48EBB2) needs both, needs the acting villager to be female, rolls
  `ChanceOfPregnancy` on the mother and calls `Impregnate` 0x4864D0. The step is queued by behaviours 0xD6, 0xDE and
  0xE8; the player's drop starts "try for a baby" behaviours 0x127 / 0x128 (0x4412E7, 0x441305), and the villager
  AI at 0x494472 can start 0x127 too. How often the AI does so: UNCONFIRMED. VERIFIED-C (call sites).
- **Conception odds** `ChanceOfPregnancy` 0x48FC10 (VERIFIED-E, `t_misc.py`; father 30, both fertility F):

| Mother age | F 1 | F 25 | F 50 | F 75 | F 100 |
|---|---|---|---|---|---|
| 18-30 | 39.0% | 55.1% | 73.1% | 89.0% | 100% |
| 31 | 17.0% | 33.0% | 51.0% | 67.1% | 83.0% |
| 35 | 9.0% | 25.0% | 43.0% | 59.1% | 75.1% |
| 40 | 0% | 15.0% | 33.0% | 49.0% | 65.1% |
| 45 | 0% | 5.0% | 23.0% | 39.0% | 55.1% |
| 50 | 0% | 0% | 13.0% | 29.0% | 45.0% |
| 51+ | 0% | 0% | 0% | 0% | 0% |

  Formula: rand(100) < 105 - (100 - motherF)/3 - (100 - fatherF)/3; fathers over 40 lose (years - 40)/5 (45: -1,
  50: -2, 60: -4, 70: -6 points); mothers 31..50 lose 2 x (years - 20); over 50: 0. Fertility is 15..89 at creation
  (rand(75) + 15), kept 1..100. VF1 has no "first try always succeeds" tip rule (VF2 has).
- **Patcher: Allow Older Pregnancies** (on by default): the call at 0x48EB8C is retargeted to the DLL's
  `ChanceWrapper`. When the older parent (mother age / 20, father age / 20 as passed) is **50 or older**: chance =
  the same sum without the mother-over-50 cut-off, x 10 tenths, capped at (60 - age) x 10 up to 59, 69 - age from 60
  to 68, then 1; at least 1 tenth; success if `GetRandom(1000)` < tenths. Otherwise the stock call. Emulated
  (`t_preg.py`, every roll value, MSVC weights): cap **10.07% at 50, 9.06% at 51, 5.04% at 55, 1.01% at 59, 0.91% at
  60, 0.40% at 65, 0.10% from 68**, floor 0.10%; mother 30 F50 with father 50: **71.06% off, 10.07% on**; father 60:
  69.06% / 0.91%; father 70: 67.07% / 0.10%; mother 45 F25 father 50: 3.00% / 3.02%; under 50 both: unchanged.
  VERIFIED-E
- **Patcher: no failed-try wait** (the store at 0x48EC70 jumps to the DLL): skipped while Allow Older Pregnancies is
  on and the head (family record parent 1) or spouse (parent 2) is 50 or older, or while Private Adult Romantic Time
  (on by default) is on and the couple cannot conceive (six children recorded; or same sex with Enable Same-Sex
  Marriage on). Emulated (`t_family.py`): 49/50 and 50/30 not stored; 50/30 with Allow Older Pregnancies off stored;
  six children not stored, stored with Private Adult Romantic Time off; five children stored. The mother's trend -50
  (0x48EC76) still runs. VERIFIED-E
- **Patcher: Up to 28 Children** (off by default, experimental): vf1fun.dll loads vf1kids.dll, whose Startup checks
  its pins and hooks `EmptyOffspringSlots` 0x4816E0 = min(28 - children, free villager slots) and `AddOffspring`
  0x481AA0 (children 7..28 kept outside the tree record). Emulated (`t_kids.py`): with 6 children 22 places, each
  added child one fewer, 0 at 28; the tree record still counts 6; off: stock 6. VERIFIED-E
- **Twins / triplets** (`Impregnate`, VERIFIED-C): bonus = (Matriarch fertility - 85 if > 85) + (Patriarch
  fertility - 85 if > 85). Twins if rand(100) < 7 + bonus and at least 2 free child slots; then triplets if
  rand(100) < 25 + bonus and 3 free slots. With no bonus: single 93.0%, twins 5.25%, triplets 1.75%. Needs at least
  1 free slot (6 children per generation). When population <= 6 the baby's sex balances the house (0x48BBF0).
- **Length**: delivered on the unit after conception + 20: **21 units = 7 h / 3 h 30 m / 1 h 45 m**
  (emulated: stamp 600, still pregnant processing units 618..620, delivered at 621). Babies are spawned hidden at
  conception (gs+0x1B120/24/28, file 0x1B130) and shown at birth. VERIFIED-E
- **Cooldown** gs+0x1B150 (real seconds, file 0x1B160):
  - set at a birth processed live: real time + 600 x (5 - motherDesire/20) x (5 - fatherDesire/20) s (desire =
    "Wants kids?" rec +0xF8, 5..94 at creation): **10 min .. 4 h 10 min, any speed**; 1 when there is no Patriarch;
  - a failed conception roll: real time + 1,200 s (20 min), mother's trend -50 (0x48EC55);
  - Marry sets 1.
  - It is read only by the drop handler (0x4412D2): before it passes, a drop gives the "too soon" behaviour and moves
    the cooldown to now + 3,300 s if it was more than an hour away. VERIFIED-C.
- Save: rec +0xCC conception age, +0xD0 babies expected; GameStats+0x08 babies born.

## 7. Careers and salary

- **Assignment** `CVillagerSkills::Reset` 0x48EFF0: career = rand(108), level 0, salary from the table. 108 careers
  with names (string 0x112 + id) and 8 level salaries: `careers.tsv` (`careers.py`). `CareerType` 0x48F080: ids
  0..29 type 1, 30..78 type 2, 79..107 type 3 (the three career rooms; which room is which: UNCONFIRMED). Levels
  Beginner, Novice, Apprentice, Licensed, Practiced, Accomplished, Exceptional, Master (0x1C1..0x1C8). VERIFIED-C
- **Work roll** 0x48F050: success if rand(160) < 10 x level + 90: emulated **56.30% / 62.56% / 68.82% / 75.07% /
  81.32% / 87.55% / 93.77% / 100%** for levels 0..7. Called from work behaviours (0x45D45F, 0x4711D4, 0x47EEB0);
  how often a villager works: UNCONFIRMED. VERIFIED-E (the roll)
- **Advance** 0x48F590 (VERIFIED-E, `t_career.py`): pay = salary x 3 x 0.01 per success; progress +
  (20 / (level + 1)) x 7 / 3 / 2 / 1 (levels 0 / 1 / 2 / 3-6) x the career room's level (1..3; none at Master).
  Progress 3,000 = promotion (level + 1, new salary, progress 0, life event 3, everyone celebrates). Successes per
  promotion at room level 1: 22, 100, 250, 600, 750, 1,000, 1,500 (room 2: half; room 3: 8, 34, 84, 200, 250, 334,
  500). Award events force progress 3,001.
- **Unwatched work** 0x488F80 (catch-up units only): count = an AI value (villager +0x6D44 / +0x537C / +0x7384 by
  career type) / 400, 0 if pregnant, / 8 if sick; each count has a 1-in-6 (16.67%) chance of a **paid** advance.
  The AI value's meaning: UNCONFIRMED. VERIFIED-C
- **Salary** every 3 units: salary / 8 (section 2) = **salary / 8, / 4, / 2 per real hour** on Slow / Normal /
  Fast, whether or not the villager is at work. VERIFIED-E
- Room upgrades: CTech levels cost 0 / 5,000 / 15,000 (`CTech::GetPrice` 0x4229D0); purchase path UNCONFIRMED.
- Save: rec +0x140 career, +0x144 level, +0x148 progress, +0x14C salary.

## 8. Money, interest and the Special Upgrades

| Item | Rule | Save | Status |
|---|---|---|---|
| Balance | float CMoney 0x50C60C; a payment that would go below 0 leaves 0 (emulated: -500 + interest -> 0) | 0xDBC8 | VERIFIED-E |
| Interest | `UpdateInterest` 0x422830: whole game days (86,400 game s) since the due date; pays balance x 0.1 x days (+0.005) and moves the date on by those days. **No cap on days** (emulated 1, 2, 3, 7 days: +100, +200, +300, +700 on $1,000). Differs from VF2 (max 2 days). | next due 0xDBCC | VERIFIED-E |
| Rate | the double 0.1 at 0x4B4520 (10% per game day: 48 h / 24 h / 12 h real); the Bank dialog's "10%" label reads the float 10.0 at 0x4B4528 | | VERIFIED-C |
| When paid | called by the happiness state (every 3 units), the Bank and store dialogs and events, so a gap is paid in one lump | | VERIFIED-C |
| New game money | $50..189 (`Money.Set(rand(140) + 50)` in the adoption scene) | | VERIFIED-C |
| Patcher: Clamp Max Money and Food | on by default: every frame (`VF1Fun_Tick`, any scene) money > 4,000,000,000 is set to 4,000,000,000. Emulated: $5,000,000,000 -> $4,000,000,000; off: stays | | VERIFIED-E |
| Patcher: Brokerage Account | Special Upgrade, $10,000 (setting "Add visible mobile version purchases", on by default): the four interest operands (0x422815, 0x422869, 0x415A80, 0x415887) point at the DLL's rate. Emulated `UpdateInterest`: bankRate 11 -> **+$110.01 a day on $1,000** (3 days $330.01), 1 -> $10.01. `BuyBrokerage` run: 10 -> 11, again -> 1, again -> 3 | Slot N.ini `BankInterestPercent` | VERIFIED-E |
| Patcher: interest-rate cheat | Cheat Upgrades (on by default): settings.ini [Cheats] `InterestRate` 1..11 read at Startup, used instead of the family's rate. Emulated: 5 -> $50.01 a day, also with bankRate 11; 12 ignored (10%) | settings.ini | VERIFIED-E |
| Patcher: Food Club | Special Upgrade, $10,000: `VF1Fun_Tick` (main scene) delivers n = whole game days since the last, each +500 food (saturating) and `UpdateNutritionAllVillagers` for groups 0, 2, 1, 3 (24 real h); last += n days. Emulated: 1 / 2 / 30 / 100 days -> +500 / 1,000 / 15,000 / 50,000, groups set, next due in 1 day; a second frame adds nothing. Eating guard (jump at 0x48BDFB): hunger > 50 and food < 60 -> food + 60 before the stock block; emulated food 30 -> 87, 0 -> 57, 59 -> 116, 60 -> 57; hunger 50: no change. Prices (`GetPrice` 0x4968C0 jumps to the DLL): items 4..11 half, rounded down (emulated: $20 -> $10, $160 -> $80) | Slot N.ini `FoodClubLastDelivery` | VERIFIED-E |
| Patcher: Health Plan | Special Upgrade, $10,000: items 20..29 (the eight medicines, Baby Boost, Doctor Consultation) a quarter, rounded down. Emulated: $5 -> $1, $45 -> $11, $75 -> $18, $500 -> $125, $175 -> $43; other items unchanged | Slot N.ini | VERIFIED-E |
| Patcher: Lucky Rock | Special Upgrade, $77,777: section 15 | Slot N.ini | VERIFIED-E |
| Patcher: Maid / Gardener | Special Upgrades, $1,000 each: section 13 | Slot N.ini | VERIFIED-E |

## 9. Leaving home

| Route | Rule | Status |
|---|---|---|
| Age 19 | `AllVillagersTimeflowUpkeep` 0x489E96: when age crosses **380 units** and `CareerType` is 0 (no career): plans dropped, `SetLeftHome` (rec +0x001 = 1, +0x004 = game s), life event 5. Children get no career (`Init` below 340), so every child not made heir leaves at 19. Emulated: age 379 -> 380 leaves with no career, stays with a career, nothing while paused. | VERIFIED-E |
| Talent Scout (event 58) | pop-up, needs a child; choice A sends the event's target away | UNCONFIRMED (the harness had no target villager) |
| After leaving | the villager keeps its slot, is saved, never ages or updates again, is not Matriarch / Patriarch, but `Population` 0x48AC90 still counts it (it checks only present and health) | VERIFIED-C |

The game's own name for this (college / boarding school): UNCONFIRMED (no reader of the college strings traced).

## 10. Dating, marriage, adoption, next generation

| Item | Rule | Status |
|---|---|---|
| Marriage e-mail timer | gs+0x1B154 (game s, file 0x1B164). **now + 180 s** after the founder or heir is adopted (0x436931); when the dating scene opens (0x4385B0): now + 300 x proposals so far (gs+0x1B158) + 600 per year the single head is over 26. When due, with exactly one present living at-home 14+ villager and a family record that `CanMarry`: e-mail 2 (dating). The first one comes 6 / 3 / 1.5 real min after the adoption. | VERIFIED-C |
| Candidate | `GeneratePeepCandidate` 0x4383D0: age = head's age + 20 x (rand(6) - 3) units (**-3..+2 years**), **opposite sex** (`sete dl` 0x43844D); dowry rand(175) + 35 = **$35..209**, doubled with 15.01% (0x4384F9). Reroll discards the previous candidate. | VERIFIED-C |
| Marry | only when both Matriarch and Patriarch exist (0x4382BF): cooldown 1, dowry paid, `UpdateParents` (spouse in record parent 2), life event 1 | VERIFIED-C |
| Founder | `CAdoptionScene::GeneratePeepCandidate` 0x436540: sex rand(2), age 20 x (24 + rand(6)) units (**24..29 years**) | VERIFIED-C |
| Next generation | `ReportDeath` sets "next generation" when a parent with children dies while a child survives; the family-tree screen offers it; choosing an heir runs `StartNextGeneration` 0x481B30 and **hides every other villager** (0x4368F0). No remarriage while children are in the record. | VERIFIED-C (code); heir choice is player input |
| Child limit | 6 per generation (`EmptyOffspringSlots` 0x4816E0); 30 villager slots; 30 generations | VERIFIED-C |
| Patcher: Up to 28 Children | off by default, experimental: 28 per generation, the tree record keeps 6 (section 6) | VERIFIED-E |
| Patcher: Next Generation at 60 | Allow Older Pregnancies (on by default): the Family Tree's flag call at 0x439390 is retargeted to the DLL's gate: the stock flag, or a surviving child (`CountSurvivingChildren` 0x481850 > 0) and the oldest present, at-home, living villager 60 or older. Emulated (`t_family.py`): oldest 59 no, 60 yes (either parent), no surviving child no, setting off: the stock call | VERIFIED-E |
| Patcher: same-sex candidates | Cheat Upgrades (on by default), the Family page's Enable Same-Sex Marriage (per family, off until switched on): the spawn call at 0x43845F is retargeted; the candidate gets the head's own sex. Emulated `GeneratePeepCandidate` up to the spawn: stock / off opposite sex, on same sex, for either head | VERIFIED-E |
| Little Visitor (events 49 / 50) | pop-up; choice A adds a child (`AddOffspring` with no parents in the bio, save doc) | UNCONFIRMED (the harness had no target villager) |
| Adoption Day (41) | everyone runs behaviour 0x48AB50 group action; no family change | VERIFIED-E |

## 11. Island events

**Timing** (`UpdateScene` 0x445271..0x445358, every frame, VERIFIED-C): when game seconds >= gs+0x1B14C (file
0x1B15C; first one 900 game s after a new village, 0x424368) and Population > 0, a random villager is picked
(0x48A490); if that villager is alive, fully caught up (age = processed age) and no e-mail is pending: **66.06%**
(rand(100) < 66 at 0x4452FC: 66 x 328 = 21,648 of 32,768; corrected 2026-10-27 from 66.02%)
queue an island-event e-mail, **33.94%** fire a pop-up event now; either way the next check is **now + 3,600 game s
= 2 h / 1 h / 30 min real** (paused: never, the game clock stops). Otherwise nothing happens and the check repeats next frame.
Selection (`0x41B1F0`, VERIFIED-C): uniform (rand(count)) among events 1..71 whose `CanFire` (vtable +4) is true and
whose e-mail flag (vtable +0x14) matches; the "fired" byte 0x502048+i is written and never read, so events repeat.
Opening the e-mail fires an e-mail event (0x41B3A0). Island state is not saved.

**Registry** (71 events, built by running the constructor 0x419EE0: `t_events.py` -> `events_registry.tsv`). Effects
from running CanFire / CalcAward / ImpactGame as linked in a test house (mother 30, father 31, child 10, baby 3,
$1,000, 500 food): `t_evfx.py` -> `events_emulated.txt`. Award ranges are exact (every roll forced to 0 and N-1).
"target" = the event acts on a villager the dialog supplies; those rows are UNCONFIRMED.

| # | Event | Kind | Effect (choice A / B) | Status |
|---|---|---|---|---|
| 1 | A Secret Admirer | e-mail | none (CanFire false in the test house) | VERIFIED-E |
| 2 / 3 | Electric Bill Correction (error / gift) | e-mail | -$5..24 / +$5..24 | VERIFIED-E |
| 4 | Spam "Funny" | (never) | CanFire is the shared `return false`: never fires | VERIFIED-C |
| 5 / 6 | Professional Association Fee / Rebate | e-mail | -$5..7 / +$5..14 | VERIFIED-E |
| 7, 8 | Professional Network, Professional Association Award | e-mail | career advances on a target | UNCONFIRMED |
| 9 | Infringement Complaint | e-mail | none seen | UNCONFIRMED (target) |
| 10 / 11 | Tax Audit (fee / gift) | e-mail | -$100 / +$100 | VERIFIED-E |
| 12-15 | Spam (Bigger Brain, Nigerian Lottery, Car Insurance, What's What) | e-mail | none | VERIFIED-E |
| 16-18 | Old Friend (good / bad / angry) | e-mail | none | VERIFIED-E |
| 19 | Oh! A collectible! | e-mail | a forced-rare collectible (`Add(-1, .., true)`) | VERIFIED-C |
| 20 | My Weather Machine | e-mail | visual weather only (VF1 has no weather type) | UNCONFIRMED |
| 21 | An extra hammock | e-mail | everyone runs to the yard (behaviour) | VERIFIED-E |
| 22, 23, 24 | Birthday present, Preferred Customer Rebate, Craft Fair | e-mail | +$10..50 / +$5..79 / +$35..45 | VERIFIED-E |
| 25 / 26 | The Rebate (deny / accept) | e-mail | none / +$50 (CanFire false in the test house) | VERIFIED-E |
| 27, 28 | Helpful Child, Bad Cookies | e-mail | +$5..54 / -$5..100 | VERIFIED-E |
| 29, 30, 33, 35 | Office Collection x2, Overdue Book, Bake Sale | e-mail | -$4..40 / -$5..50 / -$5..50 / -$6..60 | VERIFIED-E |
| 31, 32, 34 | Best Landscape Award, Kite Contest, Hot Dog Contest | e-mail | +$5..50 / +$8..80 / +$5..50 | VERIFIED-E |
| 36 | Neighborhood Children's Association | pop-up | -$20 (2 children) | VERIFIED-E |
| 37, 38 | Earthquake, Aesthetic Society | pop-up | CanFire false in the test house | UNCONFIRMED |
| 39 | Birdwatcher Society | pop-up | +$25 / 50 / 75 / 100 | VERIFIED-E (CanFire false in the test house) |
| 40 | Allergy Season | pop-up | random villagers get symptom 6 | VERIFIED-E (count UNCONFIRMED) |
| 41 | Adoption Day | pop-up | everyone celebrates | VERIFIED-E |
| 42, 43 | TV Night, BBQ Party | pop-up | everyone does the activity (CanFire needs the item) | VERIFIED-E |
| 44 | The Broken Window | pop-up | +$1..30 (rand(30) + 1) | VERIFIED-E |
| 45, 46 | Photo Contest, Community Association | pop-up | +$25..125 / -$20..100 | VERIFIED-E |
| 47, 48 | Blowing Trash, Free Lawn Service | pop-up | 5..12 wrappers in the house / 5..12 weeds in the yard | VERIFIED-E |
| 49, 50 | The Little Visitor | pop-up | A: a child joins | UNCONFIRMED (target) |
| 51-53 | Small Package, Medium Brown Box, Sealed Green Bag | pop-up | A: a tray item | UNCONFIRMED (target) |
| 54 | A Tiny White Box | pop-up | A: food x 2/3 (500 -> 334) | VERIFIED-E |
| 55 | Scratch-Off Lottery Ticket | pop-up | none seen | UNCONFIRMED |
| 56 | The Wrong Address | pop-up | A: -$100 | VERIFIED-E (what you get: UNCONFIRMED) |
| 57 | The Delivery Truck | pop-up | none seen | UNCONFIRMED |
| 58 | The Talent Scout | pop-up | A: the target child leaves | UNCONFIRMED (target) |
| 59 | The Beauty Contest | pop-up | A: -$10 | VERIFIED-E (any prize UNCONFIRMED) |
| 60-62 | Landscaping / Housekeeping / Total House Care | pop-up | A: -$20 weeds removed / -$20 socks, wrappers, cobwebs, smudges removed / -$50 all (house_store.md) | VERIFIED-E (money) |
| 63 | The Mysterious Collector | pop-up | resets collections (house_store.md); CanFire false in the test house | UNCONFIRMED |
| 64 | Water Pressure Surge | pop-up | B: five leaks (props 0x1B, 0x1C, 0x1E, 0x19, 0x1A) | VERIFIED-C (emulation stopped in `SetProp`) |
| 65 | Professional Career Training | pop-up | A: -$250 and a promotion of the target | VERIFIED-E (money) |
| 66 | The Trainer | pop-up | A: -$5 and **food set to 0** | VERIFIED-E |
| 67 | The Cooking Class | pop-up | A: a kitchen mess (props) | VERIFIED-C (stopped in `SetProp`) |
| 68 | The Power Failure | pop-up | A: food reset to 50..99 (`CFoodStore::Init`); B: a random villager gets symptom 2 | VERIFIED-E |
| 69 | Career Change Counselor | pop-up | A: a new career for the target | UNCONFIRMED (target) |
| 70 | The Rare Bird | pop-up | none seen | UNCONFIRMED |
| 71 | School Fund-raiser | pop-up | A: -$25, +100 food | VERIFIED-E |

Per-event odds of firing = 1 / (number of eligible events of its kind) at each check.

**Roll the Dice** (patcher setting Roll the Dice, on by default; `vf1fun.cpp`): $500, then `FireEvent` 0x41B360
(pop-up events, the same uniform pick); if no pop-up event can fire the $500 is refunded. Emulated (`t_dice.py`: the
DLL's store HandleMessage with the Upgrades dialog answered "Roll the Dice, yes"): FireEvent true -> -$500; false ->
$0 and the refund message. The money is VERIFIED-E, the pick VERIFIED-C, so the page line is VERIFIED-C.

## 12. Weather

Day and night follow the PC clock (section 1). The sky is the object 0x8352A4 (state +0, forced next +4, next change
+8 on the CGameTime clock): states 0..3, the bottles set 3 (rain) and 0 (sunshine); see section 24. The action
records' "sky ==" field (+0x2C40) compares with its state. The Weather Machine e-mail exists (event 20); what it
changes: UNCONFIRMED.

## 13. Messes and house malfunctions

| Item | Rule | Real time | Status |
|---|---|---|---|
| Mess spawn | `CCollectableItem::Update` 0x414BF0 (every frame, skipped while speed >= 999): every 300 game minutes (population < 4) or **150** (4+), the elapsed count of items spawn in free junk slots (30 shared, house and yard): rand(100) < 20 and no cobweb: **a cobweb** at (0x3DE, 0x2D9); < 30: weed (yard); < 55: sock; < 80: candy wrapper; else dirt smudge (house). With a cobweb already out, rolls below 20 give a weed. The population >= 6 rate (k = 3) is never taken because the >= 4 test comes first. | every 10 h / 5 h / 2.5 h, or 5 h / 2.5 h / 1.25 h with 4+ people | VERIFIED-C |
| Spawn odds per item | rand(100) at 0x414EB4: cobweb < 20 **20.02%** (if none out), weed < 30 **10.01%** (**30.03%** with a cobweb out), sock < 55 **25.02%**, wrapper < 80 **24.99%**, smudge **19.96%** (exact over rand()'s 32,768 values; corrected 2026-10-27 from the rounded 20 / 10 / 25 / 25 / 20%). Every mess owed since the last (game minutes / 300 or 150) is placed at once, as far as the free places go (0x414E6D..0x414F8F) | | VERIFIED-C |
| Counts | socks +0x6F8, weeds +0x6FC, wrappers +0x700, smudges +0x704, cobwebs +0x708 of CCollectableItem 0x501858; feed happiness (section 2) | | VERIFIED-C |
| Blue sock (0x7E) | the expiry check (0x414C71) removes types <= 0x7E once their expiry passes; whether a spawned 0x7E sock vanishes at once (house_store.md) | | UNCONFIRMED (not emulated) |
| House malfunction | 2-second step 0x444ECD: rand(800) == 1 (**1 in 800 per 2 s, mean 26.7 real min, any speed and also while paused**), none of props 0x16, 0x19, 0x1A, 0x1B, 0x1C, 0x1E, 0x1F, 0x20 active: rand(8) picks one; each is skipped while its permanent-fix flag is set (gs+0x25C/0x20C/0x21C/0x27C/0x22C/0x23C/0x26C/0x24C) | | VERIFIED-C |
| Kitchen garbage | gs+0x188 level, full at >= 20 (`AddGarbage` 0x423C50) | | VERIFIED-C |
| Patcher: Maid / Gardener | Special Upgrades ($1,000 each): `VF1Fun_Tick` (main scene): when the game seconds pass the visit time it moves on 3,600 game s and, only if `CNight::IsDayTime` 0x491630, `RemoveAll` 0x413B80 for 0x7E, 0x84, 0x8C, 0x8E (Maid: socks, wrappers, cobwebs, smudges) or 0x88 (Gardener: weeds). Emulated (`t_house.py`, IsDayTime answered day / night): day: every listed type removed, the other kept; night: nothing removed, the timer still moves an hour; not due: nothing. The counts follow on the next `Update` (it recounts every frame, 0x414C03) | 2 h / 1 h / 30 min | VERIFIED-E |

Prop names (sink and toilet leaks, clogged shower, dryer lint fire, power): the FreakOut strings 0x80..0x84 exist;
the prop-to-name pairing is UNCONFIRMED.

## 14. Food

| Item | Rule | Save | Status |
|---|---|---|---|
| Store | `CFoodStore` 0x50C550, int, floor 0, no ceiling (`Adjust` 0x4221B0) | 0xDA3C | VERIFIED-C |
| Start | 50..99 (`Init` 0x422160: 50 + rand(50)) | | VERIFIED-C |
| Groceries | +150 per bag (items 4..7), organics +250 (8..11); food groups 24 real h (section 2) | | VERIFIED-C |
| Eating / waste / starvation | section 2: 3 food per hungry villager per unit | | VERIFIED-E |
| No daily food tick | food changes only through eating, bags and events (and, with the patcher, the Food Club, section 8) | | VERIFIED-C |
| Overflow | `Adjust` checks the floor only for a loss (amount <= 0), so food added past 2,147,483,647 wraps negative. Emulated: 2,147,483,600 + 150 -> -2,147,483,546 | | VERIFIED-E |
| Patcher: Clamp Max Money and Food | on by default: every frame a negative food count becomes 2,147,483,647. Emulated: the wrapped value above -> 2,147,483,647 after one `VF1Fun_Tick`, also in another scene; off: stays negative | | VERIFIED-E |

## 15. Collectibles

| Item | Rule | Real time | Status |
|---|---|---|---|
| Spawn | every frame while speed < 999: rand(6,600) < 3 (0x414DF4) -> `Add(-1)` | at 30 fps: mean **73 s**, any speed | VERIFIED-C |
| What | `Add` 0x414A20: a random registered area, base + rand(4); rarity rand(100): **rare (+8) 4.00%, uncommon (+4) 13.01%, common 82.98%**; `force` gives rare. Nothing spawns if that item is out, carried, or (photo pieces) owned. Insect areas need a garden state, photo areas gs+0x16C. | | VERIFIED-C |
| Patcher: Lucky Rock | Special Upgrade, $77,777: `ApplyVillageEffects` writes the compares at 0x414B6F / 0x414B7C (4 / 17 -> 8 / 34) and the spawn push at 0x414DF5 (6,600 -> 3,300); removing it writes the stock bytes back. Emulated (`t_house.py`, 0x414B6D..0x414B87 for every roll value; the spawn roll's N read from the run): **rare 8.01%, uncommon 26.03%, common 65.97%**; spawn **rand(3300) < 3 = 30 / 32,768 (0.0916%)**, stock 15 / 32,768 (0.0458%) | twice as often | VERIFIED-E |
| Lifetime | 120 real s on the ground (+0x354) | | UNCONFIRMED (house_store.md reading, not re-traced) |
| Sell | duplicates $5 / $15 / $50 | | VERIFIED-C (house_store.md) |

## 16. Store rotation and sales

| Item | Rule | Real time | Status |
|---|---|---|---|
| Specials | store slots 8..13 refresh every 0x3840 = 14,400 **real** s (0x496D80 compares `GetSecondsFromGameStart` 0x4036D0, time() since the start, not the game clock 0x422320; due = now + 14,400) | 4 h at every speed, also paused and closed | VERIFIED-C (0x496D80 read 2026-10-27) |
| On Sale | one grocery (4 + rand(8)) at half price every 0xA8C0 = 43,200 game s (0x496CD0 reads 0x422320; due = now + 43,200) | 24 h / 12 h / 6 h | VERIFIED-C (0x496CD0 read 2026-10-27) |
| When | the outfit draw 0x496C70, the sale 0x496CD0 and the specials 0x496D80 run only from the store scene's activation 0x4498C0 (0x4498E7..0x4498FB), so each draw comes at the first opening of the store page after its time | | VERIFIED-C (2026-10-27) |
| Prices | `GetPrice` 0x4968C0 (labels, buy, refund); upgrades `CTech::GetPrice` | | VERIFIED-C |

## 17. Timers (every timer found on the traced paths)

Clock: **R** real seconds since the save's start (runs while closed and paused), **G** game seconds (10/speed of
real; stopped while paused), **U** age units, **F** frames, **S** the 2-second step (runs while paused).

| Timer | Field (file offset) | Clock | Length | Slow / Normal / Fast | Status |
|---|---|---|---|---|---|
| Upkeep step | scene+0x30 | S | 2 s | 2 s | VERIFIED-C |
| Age unit | rec +0xA8 / +0xAC | R | 60 x speed s | 20 / 10 / 5 min | VERIFIED-E |
| Catch-up cap | | R | section 1 | | VERIFIED-E |
| Dead body removal | rec +0xAC | R | 240 units | 80 / 40 / 20 h | VERIFIED-E |
| Pregnancy | rec +0xCC | U | 21 units | 7 h / 3 h 30 m / 1 h 45 m | VERIFIED-E |
| Baby cooldown | gs+0x1B150 (0x1B160) | R | 600 x (5-d1/20)(5-d2/20) s; failed try 1,200 s; drop 3,300 s | 10 min .. 4 h 10 m, any speed | VERIFIED-C |
| Symptom | rec +0x10C.. | R | 6..17 h | same at every speed | VERIFIED-E |
| Food group | rec +0x130.. | R | 86,400 s | 24 h | VERIFIED-C |
| Interest | 0xDBCC | G | 86,400 s, every missed day paid | 48 / 24 / 12 h | VERIFIED-E |
| Island event | gs+0x1B14C (0x1B15C) | G | 3,600 s (first: 900 s) | 2 h / 1 h / 30 min | VERIFIED-C |
| Marriage e-mail | gs+0x1B154 (0x1B164) | G | 180 s, then 300 x proposals + 600 x years over 26 | 6 / 3 / 1.5 min first | VERIFIED-C |
| Messes | CCollectableItem+0x6F4 | G | 300 / 150 game min | 10 h / 5 h / 2.5 h (or half) | VERIFIED-C |
| Collectible spawn | per frame | F | 3 / 6,600 | mean 73 s at 30 fps | VERIFIED-C |
| Patcher: Lucky Rock spawn | per frame | F | 3 / 3,300 | twice as often | VERIFIED-E |
| Patcher: Food Club delivery | Slot N.ini `FoodClubLastDelivery` | G | 86,400 s, every missed day delivered | 48 / 24 / 12 h | VERIFIED-E |
| Patcher: Maid / Gardener visit | Slot N.ini `MaidNextVisit` / `GardenerNextVisit` | G | 3,600 s, daytime only | 2 h / 1 h / 30 min | VERIFIED-E |
| Patcher: failed-try wait | gs+0x1B150 | R | not stored with a parent 50+ or a couple that cannot conceive | | VERIFIED-E |
| Collectible lifetime | slot +8 | R | 120 s | 2 min | UNCONFIRMED (house_store.md) |
| House malfunction | per step | S | 1 / 800 | mean 26.7 min, also paused | VERIFIED-C |
| Store specials | Inventory +0x13C | R | 14,400 s | 4 h at every speed | VERIFIED-C |
| Store sale | Inventory +0x120 | G | 43,200 s | 24 / 12 / 6 h | VERIFIED-C |
| Villager positions refresh | gs+0x1B314 | R | 40 s (pushed while paused) | 40 s | VERIFIED-C |
| Autosave | gs+0x1B318 (not in the save) | R | 600 s: `AutoSaveGame` 0x423920 saves when the due time < `GetSeconds` 0x401F20 (CRT `time()`, the PC clock; no speed or pause check), then due = now + 600. First due = launch + 600 (`theGameState` ctor 0x424F32). Called at 0x423290 by `theGame::GameUpdate` 0x422D90 (vtable 0x4B5E04 slot +0x1C; `ldwGame::Run` 0x402CC0 calls it every frame; every path of its 15-way scene switch reaches the check, its only `ret` is 0x4232A5) once the start-up counter theGame+0x24 is past 6. It tail-jumps to `SaveCurrentGame` 0x4238E0: Save(0), Save(slot), Save(slot+20), the slot file a quit (`Shutdown` 0x422C10: Save(slot), Save(0)) writes. Emulated (`t_autosave.py`, the update's tail and AutoSaveGame run as linked; clock and SaveCurrentGame stubbed): overdue by 1 s -> saved, next due +600; due = now or later -> no save; the same paused (speed 1009); counter 6 -> no save | 10 min, also paused | VERIFIED-E |
| Patcher: autosave | unchanged | | the tick stub (slot 0x4B5E20, `tools/build_stub.py`) runs `VF1Fun_Tick` then jumps to the real GameUpdate 0x422D90; nothing in vf1fun touches 0x423920 or gs+0x1B318. Fix Vanilla Game Bugs (on) adds `SaveCurrentGame` after the Adopt button (`AdoptionHandleMessage`, message 8 / button 1) | 10 min, plus after Adopt | VERIFIED-C |
| Day / night | PC clock | wall | | follows the PC | VERIFIED-C |
| "Where have you been?" | CGameTime+0x30 | R | shown when the whole hours away (away / 3,600, 0x4160A8) are > 23 (`cmp edi, 0x17; jbe` 0x4161D8), i.e. away >= 24 h; the load 0x4223F0 sets away to 0 for a clock saved paused | | VERIFIED-C (corrected 2026-10-27 from "> 23 h") |

## 18. Chance index (every rand call)

`rindex.py` -> `rand_sites.tsv` (address, function, N, next instructions) and `timer_sites.tsv`. Reached code holds
**5,087 of the 5,088** `GetRandom` call sites in .text (the one not reached is 0x44CAC4) and all 178 clock sites.

| Class | Sites | Meaning |
|---|---|---|
| behaviour | 4,492 | the 316 registered behaviours (action lengths, variants, walk targets); rewards not decoded: UNCONFIRMED |
| island events | 67 | section 11 |
| other | 528 in 135 functions | frame path, upkeep, setup, UI, input |

Gameplay rolls covered above (exact odds over the game's rand): `UpdateScene` rand(800) malfunction, rand(8) which,
rand(100) < 66 island-event e-mail; upkeep 0x48BC90 rand(25) poo, rand(100) x 10 eating / waste / starvation /
sickness / recovery / old age, rand(64) x 6 newborn positions; `AdjustHealth` rand(100) (+1 damping), hunger
rand(100); `UpdateDisease` rand(1000), rand(100), rand(7), rand(250); `UpdateHealthState` rand(100) x 2;
`SetSymptom` rand(12); `ChanceOfPregnancy` rand(100); `Impregnate` rand(100) x 2; unwatched work rand(6); work
rand(160); career rand(108); nutrition rand(10), rand(3); `CCollectableItem::Update` rand(6600), rand(100), rand(4 /
6 / 3); `Add` rand(4), rand(100); `FireEvent` rand(eligible); dating rand(6), rand(175), rand(100); founder rand(6),
rand(2), money rand(140); food start rand(50); villager creation (`Init` 0x484EE0, 16 sites: looks, names, voice,
fertility rand(75)+15, desire rand(90)+5, career level 8%). The rest of the "other" class is cosmetic or UI: the 58
in 0x442B30 and 57 in 0x493210 are the largest groups, not decoded (UNCONFIRMED).

## 19. Per-save values the window can read (file offsets, 24-byte header; file = gs + 0x10)

| Value | File offset | Section |
|---|---|---|
| Header epoch (real-time base) | 0x08 (i64) | 1 |
| Speed (10; +999 paused) | 0x1B190 | 1 |
| Reverse Day/Night | 0x1B194 | 1 |
| CGameTime (speed, previous, real stamp, banked game s, real s at save) | 0xDA74 | 1 |
| Villager record n | 0xE7A0 + n x 0x6B8: present +0, left home +1, left-home game s +4, age +8, sex +0xC, name index +0x10, name +0x18, bank +0xA8, last pass +0xAC, processed +0xB0, health +0xB4, cause +0xB8, pregnant +0xCC, babies +0xD0, energy +0xDC, happiness +0xE0, trend +0xE4, hunger +0xE8, dirtiness +0xEC, poo +0xF0, fertility +0xF4, desire +0xF8, symptoms +0x104, symptom expiries +0x10C, infections +0x128 / +0x129, food-group flags +0x12C, expiries +0x130, career +0x140, level +0x144, progress +0x148, salary +0x14C | 2-9 |
| Money, next interest | 0xDBC8, 0xDBCC | 8 |
| Food | 0xDA3C | 14 |
| GameStats (start, babies born +8, max population +0x18, oldest age +0x20) | 0xDA40 | 5, 6 |
| Pending babies | 0x1B130 / 34 / 38 | 6 |
| Next island event, baby cooldown, next proposal, proposals | 0x1B15C, 0x1B160, 0x1B164, 0x1B168 | 17 |
| Owned upgrades (Air Purifier gs+0x4C, Bathroom gs+0x8C) | 0x5C, 0x9C (flag k at 0x1C + 16k) | 4 |
| Family tree (30 records x 0x6C8) | 0xECC | 10 |

The symptom, infection and food-group fields lie inside the saved 0x98-byte CVillagerState copy; their meaning is
from the code above. The mess counts' saved position inside the CCollectableItem section (gs+0x754): UNCONFIRMED.
The patcher's Special Upgrades live in `Virtual Families 1 Patcher Data\Slot N.ini`.

## 20. Open questions for the owner (nothing changed)

1. **Food groups**: `FoodGroupsActive` counts a fifth slot built from group 1's expiry byte and the career id, so a
   careerless villager (children, unemployed adults) with any group counts one extra (one more old-age year, a
   lower sickness chance at 5). Stock code; how should the window present it?
2. **No-food health loss** is certain (instead of 76%) for villagers whose name index is a multiple of 6, and the
   +1 recovery at health <= 20 needs an odd index. Stock code; show it, or describe it as "for some villagers"?
3. **Starvation and disease cannot kill by themselves** (-1 losses stop at 14; deaths record cause -1). Should the
   window say so, given the cause strings "Starvation" / "Disease" exist?
4. **Catch-up on Slow** credits 8 h 36 m 40 s for any absence between 6 h 37 m and 24 h, more than the time away
   below 8 h 37 m. Only reachable with the patcher's Slow speed, and the patcher saves at Normal, so loads use the
   Normal column. Confirm the window should show the Normal column for closed-game time.
5. **Interest has no day cap** in VF1 (VF2 caps at 2 days): a long absence pays 10% per missed game day in one lump.
6. House malfunctions roll while the game is paused (the 2-second step has no pause check).

## 21. Scripts and data (the analysis scripts are kept outside the repo; careers.tsv, events_registry.tsv, events_emulated.txt, rand_sites.tsv and timer_sites.tsv are in this folder)

The patched-game runs (section 22) are in a `patched` folder beside the other scripts: `build.bat` /
`build_kids.bat` (scratch builds with a link map), `dllemu.py` (the DLLs in the harness), `t_startup.py`,
`t_oldage*.py`, `t_getrandom.py`, `t_preg.py`, `t_family.py`, `t_store.py`, `t_foodclub.py`, `t_house.py`,
`t_dice.py`, `t_warp.py`, `t_kids*.py`, `t_samesex.py`, with their `out_*.txt`.

`vdis.py` (disassembler), `rd.py`, `xref.py` (+ `ins.pkl`), `strings.py`, `reach.py` (+ `reach.pkl`), `rindex.py`
-> `rand_sites.tsv`, `timer_sites.tsv`, `behaviours.py`, `vf1emu.py` (unicorn harness), `t_timeflow.py` (aging,
clamp, leaving home, body removal; `out_clamp.txt`), `t_phys.py` + `t_life.py` (upkeep odds; `out_life*.txt`),
`t_groups.py` (food groups, old-age table; `out_groups.txt`), `t_misc.py` (sickness, conception, interest;
`out_misc.txt`), `t_career.py` (`out_career.txt`), `careers.py` -> `careers.tsv`, `t_events.py` ->
`events_registry.tsv`, `t_evfx.py` -> `events_emulated.txt`, disassembly dumps `d_*.txt`.

## 22. The game with the patcher

The page describes the game without the patcher; a "With the patcher" line follows each line the patcher changes,
naming the setting by its manifest label and default (`PATCH_SETTINGS`, checked against `manifest.json` by the test).
Every hook `VF1Fun_Startup` installs with the defaults was listed by running it in the harness (`t_startup.py`: 86
changed runs in the image) and each was matched to the page; Up to 28 Children was run with the setting on.

| Setting (default) | What changes on the page | Evidence | Status |
|---|---|---|---|
| Cheat Upgrades (on) | Time Controls speeds; saves at Normal (section 1); Time Warp (section 1); interest-rate cheat (section 8); same-sex candidates (section 10) | `t_warp.py`, `t_store.py`, `t_samesex.py`; speeds as before | VERIFIED-C (speeds), VERIFIED-E (rest) |
| Clamp Max Money and Food (on) | money cap, food overflow (sections 8, 14) | `t_store.py` | VERIFIED-E |
| Add visible mobile version purchases (on): Special Upgrades | Food Club, Health Plan, Brokerage Account (8), Maid, Gardener (13), Lucky Rock (15) | `t_store.py`, `t_foodclub.py`, `t_house.py` | VERIFIED-E |
| Older Villager Mortality Curve (on) | the birthday roll (section 4) | `t_oldage2.py`, `t_oldage3.py`, `t_getrandom.py` | VERIFIED-E |
| Allow Older Pregnancies (on) | conception with a parent 50+, no failed-try wait at 50+, Next Generation at 60 (sections 6, 10) | `t_preg.py`, `t_family.py` | VERIFIED-E |
| Private Adult Romantic Time (on) | no failed-try wait for a couple that cannot conceive (section 6) | `t_family.py` | VERIFIED-E |
| Up to 28 Children (off, experimental) | 28 child places (sections 6, 10) | `t_kids.py`, `t_kids2.py` | VERIFIED-E |
| Roll the Dice (on) | $500 pop-up event, refunded when none (section 11) | `t_dice.py` | VERIFIED-C |

Checked and left off the page, because the page says nothing they change or the result is the same:

- Fix Vanilla Game Bugs (on): the Power Failure's "keep the food" makes the same GetRandom(GetRandom(4)) villagers
  sick with symptom 2 as the stock `ImpactGame` 0x4198E0 (only the result text now matches); the Oldest Villager
  record guard (a statistic the page does not show). The save right after Adopt is on the page, under Autosave
  (section 17).
- Private Adult Romantic Time's six-children drop (0x441287 `je` -> `jmp`): the page does not describe the stock
  "They have enough kids already!" refusal.
- Behavior Label Variants (captions; the computer's browse / video-game 50:50, 0x495558 and 0x488CA9), VF1 + VF2
  Songs, Custom Map/Game Images, Glowing Collectables: behaviour choice, sound and pictures, none on the page.
- Cheat Upgrades' one-shot buttons (money, food, villager cheats, pregnancy one-shots, Evict, Adopt New Person,
  store price multipliers, house and yard), Flea Market: player actions, not rules the page describes.

Found while checking, and corrected on the page and in section 15:

- The "too soon" drop sets the wait to now + 3,300 s (55 minutes) only when the wait is **more** than an hour away
  (0x441320..0x441343: `now + 3,600 >= wait` skips the store); the page had said "if it was under an hour".
- Common collectibles are 82.98% (27,192 / 32,768), not 82.99%.

## 23. The store, the upgrades and the patcher's purchases (2026-10-27)

Every store item, home improvement and career room, and every page of the patcher's Upgrades menu, has its own entry
on the page (groups "The Family Store" .. "Patcher: the rest of the Upgrades menu"). Sources:

- **Prices, doses, stock, names**: the item table 0x4FE1B0 + 32 x (item - 1) (+4 stock, -1 = unlimited; +8 uses,
  -1 = never used up; +0xC price; +0x10 name), and the career rooms' CTech table 0x4EF620 (0 / 5,000 / 15,000 for
  each room). `test_every_store_items_name_and_price_is_the_exes_item_table` reads both from the vanilla exe.
- **Effects** (VERIFIED-E): `UseItemOnFamilyMember` 0x442B30 (items 12..17, 30..63) and the medicine / Baby Boost
  branch of the scene's drop handler 0x4462C0 (from 0x446635), run as linked (`t_items.py`, `t_items2.py`, every
  roll forced to its lowest and highest value; Imported Candy's rand(5) forced to each outcome). Both are reached
  from the frame loop through theMainScene's vtable 0x4B6FFC slot +4 (`reach.py`).
- **Queued steps** (VERIFIED-C): the stat steps an item appends to the family member's plan, run later by
  `ProcessCurrentPlan` 0x48E350 (index = step type - 1): type 0x2D trend +n, 0x31 energy +n, 0x32 energy -n,
  0x34 hunger -n and food -n/2, 0x35 health +n, 0x38 dirtiness -n, 0x39 bathroom need +n (builders 0x48D230 ..
  0x48D710).
- **Symptom names**: the Doctor Consultation's diagnosis (0x4167E0): symptom 0 hiccups (no medicine), 1 sore throat,
  2 upset stomach, 3 headache, 4 cough, 5 skin rash, 6 blocked nose; items 20..25 cure symptoms 1..6.
- **Home improvements**: the happiness update 0x48FF30 (+10 trend each; like bonuses: TV 0x4A +35, art 0x69 +35,
  tools 0x50 +10, sleeping 0x25 +25, fish 0x19 +35, bathing 0x40 +25, exercising 0x38 +35, music 0x68 +35, pinball
  0x67 +45, resting / sunlight / sitting +25, swimming 0x1C +35, solitude / quiet / resting +25, BBQ / burgers +25,
  birds 0x20 +35; career rooms 500 x (level - 1) for cooking / computers / tools); A Box of Tools and Parts: the
  repair behaviour 0x1F adds the permanent-fix repairs 0x20..0x27 (repair handler 0x489020 sets gs+0x20C..0x27C);
  Sheets and Pillows: "Going to bed" (behaviour 2) adds energy +15; the events whose CanFire reads a flag (The
  Rebate 25: TV; Birdwatcher 39: Birdhouse; BBQ Party 43: grill; An extra hammock 21, The Wrong Address 56, The
  Delivery Truck 57, The Rare Bird 70: give the item while it is not owned).
- **Specials draw** 0x449480: items 12..17 and 30..63 with stock, never item 42; 43..46 only while their repair is
  not done; the pets unless that pet is owned (the turtle's check compares with the dog, kind 1, at 0x4495D6; the cat's
  is kind 0 and the dog's kind 1, as the drop handler sets them at 0x443DA0: cat 0, dog 1, turtle 2). Fix Vanilla Game
  Bugs makes it kind 2 (vf1fun.dll writes the compare's immediate 0x4495DC after checking the stock bytes; emulated
  2026-10-27, `tests/test_cure_and_pet_turtle.py`).
- **The patcher**: the vf1fun.dll built from this repository's native\ (unchanged since v1.3) with its own
  `CheatsProc` and `VillagerCheatsProc` run in `dllemu.py` (`t_cheats.py`, the dialog's Windows calls answered).
  Found: Cure illnesses cleared the seven symptoms but not an infection. Fixed 2026-10-27: it also clears the two
  infection flags (villager +0x2B54 / +0x2B55), as Vancomycin (0x446B65 / 0x446B6C) and the Imported Candy (0x443A0D /
  0x443A13) do; the infections keep no timer.

## 24. Actions, plans and the nine settled items (2026-10-27)

Scripts (kept outside the repo with the others): `t_beh.py`, `t_recs.py`, `t_repair.py`, `t_weather.py`,
`t_sunscreen.py`, `t_store.py`, `findcall.py`; `behaviours.py` now scans the whole registration run
0x480260..0x4813C0: **316** registered actions (0x1..0x151), not 217.

- **Plans**: an action (behaviour) function appends steps to the family member's plan (villager + 0, 0xE1 steps of
  0x30: +0 type, +0x28 n, +0x2C end / done) through the builders 0x48C6C0..0x48DE45 and the appender 0x48C470;
  `UpdatePlan` 0x489540 runs `ProcessCurrentPlan` 0x48E350 on the front step until it is done, then pops it and
  starts the next (0x48C560 / 0x48DE50); an empty plan asks the chooser 0x4886E0. Stat steps (types 0x2D..0x3B, builders
  0x48D230 trend +, 0x48D290 trend -, 0x48D2F0 happiness -, 0x48D350 energy +, 0x48D3B0 energy -, 0x48D410 hunger +,
  0x48D470 hunger - and food -n/2, 0x48D4D0 health +, 0x48D530 health -, 0x48D590 dirt +, 0x48D5F0 dirt -, 0x48D650
  bathroom +, 0x48D6B0 bathroom -, 0x48D710 garbage) change stats only when processed; the start-step cases change
  none. Type 0x46 (0x48DDE0) clears the plan and starts another action. ClearPlan is 0x48C5A0.
- **Choice** (VERIFIED-E for the values, VERIFIED-C for their meaning): the record initializer 0x482120 writes one
  0xC8-byte record per action (villager + id x 0xC8 + 0x2B98..): enabled, time windows (CNight 0x491690 sunrise ..
  sunset + 2 h; 0x4916F0 sunrise .. 10:00; 0x491750 10:00 .. 16:00; 0x4917B0 17:00 .. sunset + 5 h), stat bounds,
  age bounds (units), an owned improvement (gs + n x 16 + 0xC, n = item - 64 from the store table 0x4F1308), a prop,
  the sky state, pregnancy, sickness; the weight x3 for the record's like (+0x2C48) or dislike (+0x2C4C), /4 for the
  opposite. Hand-checked against the chooser's tests 0x488790..0x488F15.
- **Activities** (`t_beh.py`, rolls low and high): treadmill 0x5A dirt +8 trend +4, 0xDD dirt +6 trend +2 energy -8;
  radio 0xEA energy -4 trend +2 dirt +2, 0xF1 trend +4; pinball 0xDC trend +5 dirt +1 energy -3; patio 0x45, 0xC3
  none; pool 0xA6 dirt +5 energy -2 trend +3, 0xA7 dirt +8 energy -2 trend +10, 0xD7 hunger +2 energy -3 trend +1;
  hammock 0x2A trend -1; grill 0xDA hunger -7 food -3 dirt +4 bathroom +4 trend +4, 0xDB dirt +7 trend +1, 0xD8
  (record health >= 300, started nowhere) never; paintings 0xE1 ("Admiring the Magic Fish", record 3 = Collection of
  Paintings), 0xE2, 0xE3 none; fish tank 0xDE trend +4, 0xDF, 0xE0 none; TV 0x4B..0x52 and 0x12E none.
- **Magic Barker** (item 60, 0x443CD6): age >= 280 reads (0x108), else 0x48A500(6) picks a reader (14+ with a career
  room and not pregnant, or 55+; at home, living); reader +4..5 happiness; 0x48A7D0(5) +5 happiness and 0x48A830(0x109)
  "Listening to a story" for everyone at home aged <= 280 with no held place (+0x1358C == -1). 0x108 / 0x109: no stat
  steps. VERIFIED-C (picks), VERIFIED-E (plans).
- **Pets** (0x513CC0, types cat 0, dog 1, turtle 2, `0x434780`): the pet code 0x431000..0x434D00 calls no villager stat
  or action routine; every reference to 0x513CC0 is the scene, the store, start-up and the drop handler. VERIFIED-C.
- **Sky** (`t_weather.py`): 0x492280(state) sets the state and +8 = clock + 900..2399 (state 0) or 360..719; the
  bottles then call 0x4921B0(state): +4 = state, +8 = clock + 30. The update 0x492420 at clock > +8 re-applies the
  forced state with its own length, or goes to 0 after a non-zero state, or rand(4) (rerolled while equal, state 1
  rerolled at night) after 0. Emulated: rain 392..751, sunshine 932..2,431 game seconds.
- **Repairs** (`t_repair.py`): the drop-on-spot handlers 0x494880 / 0x4949A0 (wall), 0x494B20 (hose), 0x494C70
  (birdbath, 0x123 + a helper's 0x124), 0x494D90 / 0x494E30 / 0x494ED0 (floor) start sessions for age >= 280, not
  pregnant; the repair handler 0x489020: floor counter (= the kit's 1) +1 a step, done at 18; wall stage 1 -> 3, then
  +1 per step on 0x160 (0x95) / 0x164 (0x96), done at 24 and 24; hose 0x1D and birdbath 0x1E done at once.
  Emulated: floor 6 sessions / 17 steps, wall 12 sessions, hose 1, birdbath 1.
- **Sunscreen** (`t_sunscreen.py`): ClearPlan, step 9, trend +25 (0x48D230), +1..3 happiness, then NewBehavior(0x6C),
  whose steps are appended after (0x46E980 never clears): the +25 is processed second.
- **Store** (`t_store.py`): outfits: 0x496C70 draws rand(50) for each at clock > due (+0x118, due = draw + 14,400 game
  s), called on the store page opening 0x4498C0; buying 0x4969A0 copies it to +0x110 / +0x114, which every tray outfit
  (64 / 65) gives (0x496D10). The Ball (item 3) is the static first special (0x4F13A8); the first opening overwrites
  all six (draw 0x449480, or the kept specials while 0x496D80 is not due: GetSecondsFromGameStart <= 1).
- **Found, not changed**: the specials refresh 0x496D80 uses `GetSecondsFromGameStart` 0x4036D0 (real seconds), so
  it is every 14,400 real seconds at any speed, not game seconds (sections 16 and 17 and the page now say so); every outfit of a kind in the
  tray shows the last one bought's picture.
