# Render Unicode with In-Game Fonts, and the Game Text tool (2026-11-01)

Everything here was found read-only in the vanilla `Virtual Families.exe` (1.01.00) and proved by running the
game's own code, and the compiled `vf1text.dll` on top of it, in Unicorn (`tests/text_emu.py`). **Not yet
tested in a running game**: the live checks are at the end.

## The game's text

**Fonts (VERIFIED).** theStringManager (0x44FCC0..0x44FD60) makes four `ldwFont`s, each with
`ldwFont::ldwFont(name, glyph table, spacing 0)` 0x4022A0 -> loader 0x402720:

| theStringManager | Font | Sheet | Table | Height |
| --- | --- | --- | --- | --- |
| +0 | SegoeUiBold18 (buttons, most dialogs) | Images\SegoeUiBold18.png | 0x4ED538 | 18 |
| +4 | SegoeUiBold17 (achievement descriptions) | Images\SegoeUiBold17.png | 0x4EC610 | 17 |
| +8 | SegoeUiBold24 | Images\SegoeUiBold24.png | 0x4EE460 | 24 |
| +0xC | SegoeUi33 (loaded but never drawn in the game: only the exit clean-up reads it, tests/test_font_slots.py) | Images\SegoeUi33.png | 0x4EB6F0 | 33 |

A table is rows of `{character, left, top, right, bottom}` ended by character 0: 190 rows each, the characters
0x21..0x7F, the space, and 0xA2..0xFF (as signed chars). A sheet is white letters whose alpha is the coverage; the
game draws no outline or shadow. The loader moves a row past the sheet's width to the next band (0x402869; never
needed for these four) and builds a 256-entry map byte -> row (0x4028BB); a byte with no row maps to row 0, "!".

The other 15 font sheets in Images are named nowhere in the exe and never drawn: AmericanTypewriter21/27,
SFCartoonistHandBold21/28, ldwBurweed27, ldwarialbold, SegoeUi20/27, SegoeUiBold21/27/33 (the same 190 characters
in the same order), and SegoeUI33x512, SegoeUIBold17/18/24x512 (the four used fonts' letters packed into 512-pixel
bands, not in the loader's band layout). The Game Text tool offers the first eleven, "(unused in the game;
metrics not from the game)": their glyph boxes were found from the sheet by `scripts/build_vf1_glyphs.py` (190
boxes in the game's order whose edges fall on the emptiest columns, each kept near the width a game font gives
that letter; checked on the four used fonts, where the same search lands every edge within a few pixels and in
the right gap for 182..186 of 189 edges). The four x512 sheets are the used fonts again, so they are not listed
twice.

**Drawing (VERIFIED, emulated).** `ldwGameWindowImpl::DrawString` 0x409660(text, x, y, colour, font): colour
alpha 0 means the default 0xFFFFFFFF (0x4E927C); the sheet tinted for the colour comes from 0x402940 (the white
sheet for white, else a cached copy with every pixel ANDed with MapRGBA(r, g, b, 255), r = colour byte 0). Per
byte: "\n" goes to the next line (y += height, x back); a box 0 wide is skipped; otherwise the box is clipped
(0x407E60) and drawn with SDL_UpperBlit (colour alpha 255) or BlitRectWithAlpha 0x404C30 (alpha/255), and x moves
by the box width plus the spacing. `ldwFont::GetWidth` 0x402320(text, scale) adds trunc((width + spacing) x scale)
per byte and takes the widest line, minus the spacing. 0x409450 is the same draw for the first n bytes, with a
measure-only flag; the justified word wrapper (0x409DA9..0x40A0B9) splits text at spaces and measures each word
with it. `tests/test_vf1_game_fonts.py` runs these on every font and compares every box, place, width and pixel
with `patcher/vf1_game_fonts.py`.

**Typing (VERIFIED).** SDL2 delivers typed text as SDL_TEXTINPUT (UTF-8, after dead keys, Alt codes and an input
method's composition). ldwGame's event loop posts it to the focused text box as message (5, 0, character), but
only when the event's text is exactly one byte (0x4049BB): any accented letter, Alt code or input-method word is
dropped. The box's handler 0x40DA70 refuses a key from 0x80 (it is a signed char, 0x40DB0F) and anything past the
box's limit (the family name box: 20, 0x41C67C), deletes the last byte on Backspace, and ends on Enter or Tab.
`GetText(buffer, size)` 0x40D740 is strncpy then buffer[size - 1] = 0: the family name keeps 19 bytes.

**Encoding.** The game treats text as bytes; its fonts can draw Latin-1 (0xA2..0xFF) but nothing can type those
bytes, so every stock name is printable ASCII.

## The patch: Render Unicode with In-Game Fonts (`RenderUnicodeInGameFonts`, on by default)

`native/vf1text/vf1text.cpp`, built by `native/build_text.bat`, installed as
`Virtual Families 1 Patcher Files\vf1text.dll` with `Unicode Text\<font>.png/.txt` beside it, loaded by vf1fun.dll
(`LoadTextCompanion`) only while the setting is on. Six jumps at function entries, installed all or nothing
after checking each site's stock bytes:

| Site | What the DLL does there |
| --- | --- |
| 0x402320 GetWidth | the stock measure, one whole character at a time |
| 0x409660 DrawString | the stock draw, one whole character at a time |
| 0x409450 counted draw | the same; a character the count would cut is not drawn |
| 0x40D740 GetText | the stock copy, never cutting inside a character |
| 0x40DA70 text box handler | the stock rules, plus whole code points (posted as 0x40000000 + code point) added as UTF-8 when they fit, and Backspace deleting a whole character |
| 0x4049BB SDL_TEXTINPUT | one byte goes on as before; longer text is posted a character at a time |

**Storage: UTF-8 in the game's own fields** (the same approach as the Virtual Villagers patcher). ASCII is
unchanged; any other character is UTF-8 inside the same byte field, which is never made bigger. A string that
is valid UTF-8 is UTF-8; any other string is read one byte per character (Windows-1252; its five unassigned bytes
as Latin-1), so an old or hand-edited save reads as before. A name is cut only between whole characters (grapheme
clusters: a letter with its marks, emoji with skin tones, joiners and variation selectors, a flag's two letters).
The patcher's readers share one rule, `patcher/vf1_text.py` (the save reader, the Family Tree and genealogy, the
Family History log reader, Rename Family, Copy Player Slot, the Game Text tool); the DLL uses the same cluster
table, generated from it (`scripts/build_vf1_text_tables.py`, checked by `tests/test_vf1_text.py`).

**What the stock game does with such a save (VERIFIED, emulated).** It loads and saves the bytes unchanged, and
draws each byte as its Latin-1 letter ("Zoë" as "ZoÃ«"; bytes 0x80..0xA1, which no sheet has, as "!"). Nothing
crashes: every byte has a row (`test_the_stock_game_draws_utf8_names_as_latin1_letters_without_harm`).

**Where VF1 differs from the Virtual Villagers patcher.** Same storage rule and drawing order. VF1's fields are
fixed bytes in the save (family name 19, slot menu 20, a person's name 24, parents' names 25), and a name
that fits is stored as it is; a longer one as its short form, with the whole name in the save's Names file (One
character limit for every name box, below).

**Drawing.** Each whole character is drawn as the game draws its own letters (the same clip, the same blit, the
same AND tint, the same advance):
1. the game's own letter: U+0020..U+007F and U+00A2..U+00FF, and control characters as the game's row 0, exactly
   as the stock game;
2. a patcher-made letter (`payload\UnicodeText\<font>.png/.txt`, about 2,970 per font: Windows-1252's extra
   letters, Latin Extended-A and -B, IPA, Greek and Greek Extended, Cyrillic, Vietnamese, punctuation, currency,
   letter-like symbols, number forms, arrows, maths, shapes, symbols and dingbats);
3. a letter Windows draws on the spot in the font's style, kept for the session (16 pages of 1024 x 16 bands per
   font): the first face of Segoe UI, Segoe UI Historic, Segoe UI Symbol, Segoe UI Emoji, Yu Gothic, Microsoft
   YaHei, Malgun Gothic, Nirmala UI, Ebrima, Microsoft JhengHei, Leelawadee UI, Gadugi, Myanmar Text, Javanese
   Text, Mongolian Baiti, Microsoft Himalaya, Microsoft Yi Baiti, Microsoft New Tai Lue, Microsoft Tai Le,
   Microsoft PhagsPa, Sylfaen, Cambria Math, Noto Sans (and Symbols, Symbols 2, CJK JP, Math) whose character map
   has every character of it;
4. else the missing-letter box.
A letter with combining marks is first composed (NormalizeString C); one that does not compose is drawn whole.

**How the letters are made** (`patcher/vf1_glyph_maker.py`, `vf1_glyph_gdi.py`). The four sheets are Segoe UI
drawn by GDI: the build fits each font's face, weight and em size to the game's own A..Z a..z 0..9 pixel by pixel
(SegoeUi33: Segoe UI 400, em 31; SegoeUiBold17/18/24: Segoe UI 700, em 15/16/21; every advance within a pixel),
its baseline (the bottom of the game's H) and a coverage curve (gamma 2.28 / 2.42) that maps GDI's anti-aliasing
to the sheet's. Then:
* a Greek or Cyrillic letter shaped like a Latin one (Α, О, а, р...) is the game's own letter;
* an accented letter is the game's own base letter plus marks: grave, acute, circumflex, tilde, diaeresis, ring and
  cedilla cut from the game's own è é ê ñ ë å ç (and capitals); the caron is the game's circumflex upside down;
  the macron the game's ¯; the dot above one dot of the game's ¨; any other mark is cut from the same letter
  drawn by Windows; each keeps its gap and place across the letter, the capital form over capitals and tall
  letters, i and j lose their dot first (ı and ȷ are made so); a mark with no room in the font's cell, a
  second mark over a capital, and ď ľ ť Ľ and the Latvian comma letters are drawn whole instead;
* everything else is drawn by Windows in the fitted style.
The DLL draws on-the-spot letters with the same GDI steps (`native/vf1text/glyph_gdi.inc`), so the game and the
tool show the same pixels; `tests/test_vf1_glyph_gdi.py` proves it through 32-bit rundll32 and inside the emulator
with the machine's real GDI.

## Use Unicode Font (overrides in-game fonts) (`UseUnicodeFont`, off by default)

`vf1font.dll`: the same source as `vf1text.dll` built with `VF1_FONT_MODE` (`native/build_text.bat`), loaded by
vf1fun.dll when this setting is on and Render Unicode with In-Game Fonts is off. The same six hooks, typing and
UTF-8 storage; every letter except line breaks and control characters (the game's own letters too) is drawn by
GDI in the chosen face, then Segoe UI, then the chain. The face is settings.ini `[UnicodeFont] Face=` (Segoe UI
when absent), and `File=` names a font file in `Virtual Families 1 Patcher Files\Unicode Font\`, loaded with
AddFontResourceExW(FR_PRIVATE) for the game only. Each game font keeps its height, baseline, weight and coverage
curve (the shipped `Unicode Font\<font>.txt` styles); its em is fitted at first use so that "The quick brown fox
jumps over the lazy dog 0123456789" is as wide in the face as the game font draws it (60% to 130% of its own em;
`FitChosenFont` = `vf1_game_fonts.fit_unicode_font`). Tools tab -> **Unicode Font...** (`patcher/vf1_unicode_font.py`)
picks the face or file, previews the four fonts as the game will draw them, and writes the section; Game Text
can preview with it too.

The two settings exclude each other (manifest `excludes`, both ways): the window unticks one when the other is
ticked; Select All Patches and Enable All Main Patches keep Render Unicode with In-Game Fonts (on by default);
Owner's Defaults keeps Use Unicode Font; Patch Selection Settings refuses ticking both at once; the command line
refuses `--enable` of both and lets `--enable` of one turn the other off.

Proved: `tests/test_unicode_font.py` runs the game's DrawString and GetWidth with the real vf1font.dll in Unicorn,
its GDI calls made by real GDI, for Segoe UI, Comic Sans MS and Arial loaded from a font file, in all four fonts:
every place, box and pixel equals the patcher's preview.

Live check: tick Use Unicode Font, patch, pick Comic Sans MS with Unicode Font..., start the game: every screen's
text is in Comic Sans, buttons and dialogs still fit, a typed accent and a Japanese name show; pick a font file and
start again.

## Names in vf1fun.dll's own windows

The Upgrades menu's windows (the Family page, Spawn Child, Adopt Outside Child, Villager Cheats, Clothing and
Hairstyles, Services) read every name by the same one rule (`native/vf1fun/text_names.inc`: UTF-8, else one byte
per character, Windows-1252) and store a typed name as UTF-8 in the 24 bytes the game gives it, cut only between
whole characters (the same cluster table, `native/vf1text/extenders.inc`); control characters and unpaired
surrogates are never stored. Before, they used the system code page, so a name like "日本" could become
"??". This holds whichever of the two Unicode settings is on, or neither (the stock game then shows the UTF-8 as
Latin-1 letters, as for any such name). `tests/test_vf1fun_names.py` runs the DLL's own code for both rules in
Unicorn and compares with `vf1_text`.

**Showing every script (VERIFIED on Windows 11, offscreen).** The windows use Segoe UI 9. With it, Windows' font
links and script fallback draw almost every script in EDIT, LISTBOX and STATIC controls, but not Cuneiform
(U+12000-U+1254F): a Cuneiform name showed as empty boxes in the Name box (the stored text was right). Segoe UI
Historic (in Windows since 10) has the same Latin letters plus Cuneiform, Egyptian, Gothic and the other historic
scripts, and the same fallback fills in the rest. So every control that shows a name (the Family page's Name box
and family line, the Villager Cheats, Services and Clothing and Hairstyles name lists) uses Segoe UI Historic at
the dialog font's size (`UseNameFont`, `native/vf1fun/vf1fun.cpp`); the rest of each window keeps Segoe UI, so
the layout is unchanged. A list box draws with that fallback only with `LBS_USETABSTOPS` (without it Turkish,
Polish, Greek and Cyrillic letters showed as boxes), so the Services list has it too. The controls stay plain
EDIT / LISTBOX / STATIC controls: a RichEdit control was tried and draws Cuneiform too, but drew Gothic as boxes
with some fonts and would change how the Name box takes text; the plain EDIT keeps its limit, its typing and
Windows' own Ctrl+C / Ctrl+V / Ctrl+X. Nothing in vf1fun.dll hooks the keyboard, filters characters or runs its
own message loop (each window is `DialogBoxIndirectParamW`'s), so copy and paste work in every vf1fun box; a
pasted name is stored by the same one rule as a typed one (`SetName` -> `StoreTypedName`).

Not fixed: the confirmation boxes that repeat a name ("Buy ... for <name>?", "Change <name>'s hairstyle?") are
Windows message boxes, drawn in the system's message font; a Cuneiform name shows as boxes there. Linear B and the
other scripts no installed Windows font has show as boxes everywhere.

`tests/test_vf1fun_dialogs.py` makes every vf1fun window for real from the DLL's own templates: every control is
in the template and made by Windows (Close, IDOK, included), inside the window in dialog units, at 96, 120 and 144
DPI and as made; each name control draws Cuneiform, Egyptian, Gothic, Latin, Turkish, Polish, Vietnamese, Greek,
Cyrillic, Armenian, Georgian, Hebrew, Arabic, Japanese, Korean, Chinese Extension B, emoji, Thai, Devanagari,
Ethiopic and Cherokee letters, one at a time, unlike a code point no font has (and with the dialog font alone it
draws Cuneiform as that box); the Name box is a plain, unsubclassed EDIT control with the same limit that keeps a
pasted supplementary-plane name exactly.

**The Family page had no Evict Family and no Close (fixed).** Each window's template said how many controls it has
in a number written by hand; the Family page said 29 for its 31, so Windows made only the first 29 and left out
Evict Family and Close (`GetDlgItem(IDOK)` failed; the window's size was right). The template now counts its own
controls. Every window closes with Close (`IDOK`), Esc (`IDCANCEL`) and the title bar's X (`WM_CLOSE`); the
Upgrades Menu has no control with ID 2, its Close is `IDOK`.

### Live checks for vf1fun's windows (not yet done)

1. Upgrades menu -> Family: the page shows Adopt New Person, Evict Family... and Close; Close, Esc and the X close
   it; Evict Family asks before it does anything (Cancel it).
2. Open every page of the Upgrades menu at 100%, 125% and 150% display scaling: every button shows whole, inside
   its window; Esc closes each page and the Upgrades Menu.
3. With a family member named in Cuneiform (e.g. U+1208D) and one in Japanese, Turkish and with an emoji: the
   Family page's family line, Villager Cheats, Services and Clothing and Hairstyles lists show the letters, not boxes.
4. Family page: type or paste a Cuneiform name in the Name box: it shows the letters; Spawn Child: the child gets
   that name in the game (with a Unicode setting on).
5. In the Name box: Ctrl+C, Ctrl+X and Ctrl+V (and the right-click menu) copy, cut and paste; a pasted name longer
   than the box stops at the box's limit.

## The Game Text tool (Tools tab -> Game Text...)

`patcher/vf1_game_text.py`: a multi-line text box; the font (the four game fonts with what they are used for,
then the eleven unused sheets, labelled); colour (white, black, the game's button colour, or any; a see-through
level as the game's alpha blit); the preview drawn exactly as the game draws (every box and advance from the exe),
on a checkerboard or a colour, at 1x/2x/4x, or "As the stock game shows it"; a character picker that searches by
name or code point and labels each character "(game)", "(patcher-made)", "(drawn by Windows: face)" or
"(missing)"; Save PNG (transparent, the game's own box or trimmed to the letters; game size, 2x, 4x or custom).

## Proved by emulation (tests)

* `tests/test_vf1_game_fonts.py`: the four fonts and tables are found in the exe; every box, place, width
  and pixel of DrawString / GetWidth / the counted draw (ASCII and Latin-1, every font) equals the tool's; tint is
  the AND; the stock game draws UTF-8 names as Latin-1 letters without harm.
* `tests/test_vf1_unicode_text.py` (the real DLL on the real exe): all six sites or none; names in French,
  German, Turkish, Polish, Vietnamese, Greek, Russian and with typographic quotes and € drawn and measured as the
  tool draws them, in every font; tint and see-through as the game's; old single-byte names unchanged; the
  counted draw never draws part of a letter; typing: one byte goes the stock way, longer text a character at a
  time (2-, 3- and 4-byte characters); the family name box at its limit (20 bytes) and one past it, with no write
  past the box's buffer or the 20-byte name buffer, and GetText keeping 9 whole "é" (18 bytes) of 10; Backspace
  deleting a whole letter, emoji with skin tone, or letter with a combining mark; numbers-only boxes and control
  characters refused.
* `tests/test_vf1_glyph_gdi.py`: the DLL's own on-the-spot letters equal the tool's, per font, through rundll32;
  and names in French, Turkish, Japanese, Chinese, Korean, Cuneiform and with emoji drawn through the game's
  DrawString with the DLL inside the emulator, the DLL's GDI calls made by real GDI, equal the tool's pixel for
  pixel, in every font.

## Live checks (not yet done)

1. Patch with the setting on (default). Start a new family; in the name box type: an accent with a dead key
   (`´` then `e`), an Alt code (Alt+0233), a Turkish letter (ı ğ ş İ) with a Turkish layout, and Japanese with
   the Microsoft IME (にほん -> 日本). Each appears whole; Backspace removes a whole letter each time.
2. Type until the box stops (20 plain letters; 10 é) and press OK: the family name shown in the game and in the
   slot menu is the stored one (19 plain letters, 9 é), with no half letter.
3. The family name shows correctly on the main screen, the slot menu, the Family Tree screen and every dialog
   that names the family, in each font size.
4. Rename Family a family to "Zoë 日本 👍" (16 of the 19 bytes) and open it: the slot menu and the game show it; the
   Family History log's rename record shows it.
5. Untick the setting, re-patch, open the same family: it loads and plays; the name shows as Latin-1 letters
   ("ZoÃ«"); quit and re-enable: the name is back, unchanged.
6. Colour: text drawn in a colour (store prices, dialogs) shows patcher-made letters in the same colour.
7. Check frame rate in the house with a long Japanese family name on screen (the letters are made once).
8. Names wider than their spot (Names fitted to their spot, below): a child named 𒂍𒂍𒂍𒂍𒂍, 山田花子太郎次郎 or 24 "W"
   stays inside its Family Tree frame with "…"; the bottom bar's name stops before "Age"; ordinary names look as in
   the stock game; the Details screen's values show whole.

## One character limit for every name box (2026-11-01)

### Release note

> **Names up to 300 characters, everywhere.** With Render Unicode with In-Game Fonts or Use Unicode Font on, every
> name box takes up to 300 characters: the family name, the slot menu's New Player, adoption, a new baby, renaming a
> family member, and the Upgrades menu's Spawn Child and Adopt Outside Child; Rename Family and Copy Player Slot
> take the same 300. It is one limit, shared with the other Fun Patchers. Characters are counted as you see them
> (a letter with its accents, an emoji with its skin tone or a flag is one), and Backspace removes one whole
> character. A long name scrolls in its box while you type it. The save itself is not changed: a name that fits
> its field is kept there exactly as before; a longer one is kept there as its short form (its start and "...",
> or "2...", "3..." when two would start alike) and the whole name is kept beside the save, in
> `Virtual Families 1 Patcher Data\Names`. The game shows the whole name wherever it shows that name, fitted with
> an ellipsis (…) only where the game leaves room for a name's usual length; the Family History log, the Family
> Tree Maker, Rename Family and Copy Player Slot use the whole name. Back Up Saves, Restore Saves and Copy Player
> Slot carry the Names files with the saves. With both settings off the game still loads and plays such a save and
> shows the short form.

### The limit and why (VERIFIED in the exe)

`NAME_LETTERS = 300` in `patcher/vf1_text.py` is the only place the number is written; `NAME_BOX_BYTES = 4 x 300
= 1,200` and the mark `"..."` sit beside it. `scripts/build_vf1_text_tables.py` writes all three into
`native/vf1text/extenders.inc` (`VF1_NAME_LETTERS`, `VF1_NAME_BOX_BYTES`, `VF1_NAME_MARK`), which vf1text.dll,
vf1font.dll and vf1fun.dll include; `tests/test_name_limit.py` checks that nothing else spells the number.

The ceiling is the LDW engine's own: `ldwTextControlImpl::SetEditable` 0x40D370 clamps every box's limit to 0x4B0
= 1,200 bytes (`cmp edx, 0x4B0` / `mov edx, 0x4B0` at 0x40D3B3) and allocates limit + 1 bytes; Fish / Plant
Tycoon's engine has the same cap. One code point is at most 4 bytes of UTF-8, so 300 characters of single code
points always fit in 1,200 bytes. A character built of several code points (a letter with several marks, a joined
emoji family) takes more: the box then stops at 1,200 bytes first (it takes a typed code point only while the text
stays within 1,200 bytes AND 300 characters). The cap is not patched past.

### The boxes (all ten `SetEditable` calls that make a name box; VERIFIED)

| SetEditable call | Stock limit | The box | Where its text goes (GetText call -> copy) |
| --- | --- | --- | --- |
| 0x41BB4F 0x41BBEF 0x41BC91 0x41BD36 0x41BDF0 | 20 | the slot menu's five names | 0x41C1BB / 0x41C207 / 0x41C257 / 0x41C2A7 / 0x41C2F4: GetText(gs+0x1B192+0x15(k-1), 0x14), then strcpy to gs+0x1B12C |
| 0x41BF15 | 20 | New Player | (the same five reads) |
| 0x41C67C | 20 | the first family's name | 0x41C72B: GetText(gs+0x1B12C, 0x14), then strcpy to gs+0x1B192 (slot 1) |
| 0x435AFB | 18 | adoption | 0x43682A: GetText(local, 0x13), then strncpy(villager+0x2A44, local, 0x19) |
| 0x437955 | 18 | a new baby | 0x43829D: GetText(local, 0x13), then strncpy(villager+0x2A44, local, 0x19) |
| 0x44A6DE | 18 | renaming a family member | 0x44BCE1 / 0x44BDDE: GetText(local, 0x13), FamilyTree::ChangeName (0x481C20, copies at most 0x19 at 0x481C3A), then strncpy(villager+0x2A44, local, 0x19) |

Not names, left at their stock limits: 0x4172A8 (an 80-byte field of a Job / Likes dialog, 0x416CF0) and
0x43F1B0 / 0x43F200 (the animation tool's 20- and 31-byte fields). The one other GetText call, 0x41C050 (the slot
menu reading a slot's label into a 20-byte local), gets the short form too.

**Where the typed text can go (audit).** The enlarged buffer is the box's own (`impl+0x30`, allocated by
SetEditable / SetText with limit + 1 bytes). Its pointer is read only by the box's own methods: SetEditable
0x40D370, SetText 0x40D430, its auto-size 0x40CFD0 (measures only), its Draw 0x40D140 (measures and draws; it would
cut the text, see below), GetTextLength 0x40D710 (its two callers, 0x41C10F and 0x41C6EC, only test for empty),
GetText 0x40D740, HandleMessage 0x40DA70 and the destructor 0x40D921. Every copy of a name into a fixed buffer goes
through GetText, which now gives the game only the short form: at most `size - 1` bytes, valid UTF-8, never more
than the stock game could store. The game's own copies after it (the strcpy / strncpy above, ChangeName's 0x19)
see only that. The full text goes only to the Names file and to the drawing hooks.

### How it works (`native/vf1text/names.inc`, in vf1text.dll and vf1font.dll)

Four more function-entry hooks, installed with the six of the first part, all or nothing, after checking each
site's stock bytes; each runs the stock code for everything it does not change:

| Site | What the DLL does there |
| --- | --- |
| 0x40D370 SetEditable | called from one of the ten name-box calls (its return address): the limit is 1,200 bytes |
| 0x40D430 SetText | a name box given a short form opens with the whole name |
| 0x40D140 the box's Draw | the stock draw deletes bytes from the end of the box's text until it fits (0x40D2B7); a name box draws a copy instead -- the end that fits while it is typed into, its start with "…" otherwise -- so its text is never cut |
| 0x409D70 the word wrapper | whole names for short forms before the stock wrapping |

and the first part's hooks do more: HandleMessage counts characters in a name box (300) and its bytes (1,200);
GetText of a name box gives the short form (`ShortFor`, the rule of `vf1_names.short_form`) and records the whole
name in the Names file of the slot the call site writes (fixed for the slot menu and the first family, the slot
being played, gs+0x1B188, for a member's name); DrawString and GetWidth draw and measure the whole name wherever a
short form is drawn, fitted with "…" into the width of as many "W" as the field holds bytes (the widest name the
stock game can show there). Every short form ends with "...", so only text with "..." in it is looked at.

**The short form** (`vf1_names.short_form`, the same in the DLL): a short form already standing for this name is
used again; a name that fits and is no other name's short form is stored as it is; else the longest start that
fits with the mark (trailing spaces dropped) + "...", then + "2...", "3..." until it stands for no other name in
any slot (a family name's short form shows in the slot menu beside the others). It is unique, so it names one
family member: it follows them wherever the game copies their name (their children's parents' names, the Family
Tree's records, their death), through Copy Player Slot, Back Up / Restore Saves and a rename.

**The Names file**: `<saves>\Virtual Families 1 Patcher Data\Names\Virtual Families<N>.ldw.txt`, UTF-8 lines
`VF1 Names 1`, then `short<TAB>room<TAB>whole name` (room: the field's bytes it was made for). Written through a
temporary file and MoveFileEx. A line is never removed: a short form no longer in the save is harmless (a new one
is never made equal to it), and the older autosave copies `<N+20>` / `<N+40>` stay readable. A line that is not
valid (no mark, too long for its room, a control character, more than 300 characters or 1,200 bytes) is left out;
a file that cannot be read is read as empty, and the save shows its short forms.

**Who else reads it**: vf1logs.dll writes the whole name in the Family History log (`Text::Name` asks
vf1text.dll / vf1font.dll's `VF1Text_FullName`); vf1fun.dll's windows show whole names, and Spawn Child / Adopt
Outside Child take 300 characters (`VF1Text_StoreName`, in the 24 bytes those windows use); the patcher's
`vf1_save.read_save`, the Family Tree Maker (`vf1_genealogy.load_village`, before the tree file and the log), the
Family History reader (an older log's short forms), Rename Family and Copy Player Slot (both write the Names file:
a long new name gets its line, the copy takes the source's file with the new name's line; a failed rename puts it
back) use `patcher/vf1_names.py`.

### Proved (tests)

`tests/test_name_limit.py`, with the REAL vf1text.dll and vf1font.dll on the REAL exe in Unicorn
(`tests/names_emu.py`): each of the ten boxes, set up from its own call site, takes 300 characters and refuses the
301st, and takes 300 four-byte characters (1,200 bytes) and nothing more, with guard bytes after every buffer the
game allocates; joined emoji stop at the 1,200-byte cap; combining marks do not count; Backspace removes one whole
character; the three other boxes keep their stock limits; for every GetText site the game's own instructions run
from the call to the end of the copy after it, with names that fit exactly, one byte past the field, 300
characters, 300 accented characters and 1,200 bytes, and nothing outside each destination field or local buffer
changes (guard bytes) while the destination holds `vf1_names.short_form`'s answer and the Names file the whole
name; short forms of names that start alike are unique and equal the patcher's; the same name keeps its short
form; a rename box opens with the whole name; DrawString, GetWidth and the word wrapper show the fitted whole name
in all four fonts; a long name scrolls in its box and the box's text is never cut; the Names file is read again
after a restart; a damaged one reads as empty. `tests/test_rename_family.py` and `tests/test_copy_slot.py`: long
names, the Names file, two names that start alike, a failed rename undone.

### Live checks (not yet done)

1. New family with a 300-character name (type until the box stops): the box scrolls; the main screen, the slot
   menu and the Family Tree screen show the whole name (with "…" where it does not fit); quit and start again:
   the same.
2. Adopt, name a new baby and rename a member with a long name and with a 300-character Japanese name; open the
   Family Tree screen and a child's parents' names; let a long-named member die.
3. Turn both Unicode settings off and re-patch: the family loads and plays and shows the short forms; turn one on
   again: the whole names are back.
4. Rename Family and Copy Player Slot with a long name; Back Up Saves and Restore Saves; the Family History log
   shows whole names; the Upgrades menu's Spawn Child with a long name.
5. Use Unicode Font with Comic Sans MS: the same checks.

## Names fitted to their spot (2026-11-01)

### The bug and its cause

With Render Unicode with In-Game Fonts on, a Cuneiform name such as five U+1208D (20 bytes of UTF-8) fits a family
member's 24-byte name field, so it is stored whole, not as a short form; but its letters are drawn by Windows and
are much wider than Latin letters (105 pixels in SegoeUiBold18, against 89 for "Christopher"), so on the Family Tree
screen it ran out of the child's frame on both sides. The fit-to-width of the previous part only looked at short
forms (text with "..." in it) and fitted them into the width of as many "W" as the field has bytes (24 W: 384
pixels), far wider than the real spot. Nothing fitted a name that is short in bytes but wide in pixels.

A second fault was found on the way: the previous part took a text box whose limit is 1,200 bytes for a name box,
but the text control's constructor 0x40D7E0 starts EVERY control with that limit (0x4B0 at 0x40D851), labels too.
So every label wider than the size it was made for was drawn cut with "…" to that size: the bottom bar's name to
the width of "Joey Joerson", and a label made for "." (most of the Details, dating and adoption screens' values) to
nothing. A name box is now also editable (+0x24, which only SetEditable sets; the label constructors 0x40DBC0 /
0x40DC90 pass 0), and labels draw as the stock game draws them, except at the spots below.

### The fix (`native/vf1text/names.inc`: `DrawSpots`, `LabelSpots`, `FitToRoom`; both DLLs)

Every fixed spot where the game draws a family member's name has its real room in the DLL, found in the vanilla exe
and its layout run in the emulator. A name (whole names for short forms first, as before) wider than its spot's room
is drawn as its longest start of whole characters (grapheme clusters), trailing spaces dropped, then "…" (U+2026; in
a name read one byte per character, the Windows-1252 byte 0x85, which is the same letter), measured with the
letters the DLL draws (the game's, patcher-made or Windows', or Use Unicode Font's). A name that fits is drawn
exactly as before. The spot is told by return address: DrawString 0x409660 and GetWidth 0x402320 use the game's
call site (their own return address, or, when they are called from inside the right-aligned 0x409CD0 or centred
0x409D20 draw, that draw's: 6 dwords up from GetWidth's return 0x409CF6 / 0x409D46, 9 dwords up from DrawString's
return 0x409D10 / 0x409D67, after its pushes of ebx, esi and edi), so the centred draw measures and draws the same
fitted name. A label's spot is the SetText call that put the name in it (ldwTextControl::SetText 0x40D700 jumps to
0x40D430, whose return address is the game's call site); the label then draws a fitted copy and keeps its own text.

| Spot | Drawn by (call site) | Room | How the room was found |
| --- | --- | --- | --- |
| Family Tree screen, first parent | DrawString 0x439C74, left-aligned, record +4 | 127 | the family row 0x439BA0 draws the name at the portrait's right + 4 (x = 147, 0x439C65) inside the parent frame familytree_parentframe.png (248 x 91) drawn at x - 8 = 26 (0x439C2E): its right edge is 274 |
| Family Tree screen, second parent | DrawString 0x439DB3, record +0xDC | 127 | the same (0x439DA5, 0x439D7F) |
| Family Tree screen, each child | centred draw 0x439F49 (0x409D20), record +0x1B8 + 0xD8 k | 93 | centred 46 pixels right of its frame's left (frame 0x439F01, centre 0x439F3B), familytree_childframe.png 94 x 74: x = centre - width / 2, so 93 pixels lie inside the frame |
| House screen, bottom bar: the selected person's name | label +0xC4, SetText 0x445710 | 141 | a left-aligned label at (61, 538) made for "Joey Joerson" (0x4446D3); not editable, so the stock draw never cuts it (the cut at 0x40D2B7 is for editable boxes only); the "Age" column's caption starts at x = 202 (0x444772) |
| House screen, bottom bar: the status line ("{name} sees {name2}.", 0x44E9B0) | label +0xE0, SetText 0x445866 | its box, 416 | a label centred in the box made for 26 "W" (0x444BDF: 187 .. 603), never cut by the stock draw |
| Every name box: the slot menu's five and New Player, the first family, adoption, a new baby, the Details screen's rename box (0x44A69E, made for 21 spaces) | the box's draw 0x40D140 | the box | as before (previous part): the end that fits while it is typed into, else its start with "…" |

Looked at and left as they are:
* The main menu's current player (label +0x138, SetText 0x447535): centred on x = 418 with no box or neighbour to
  run into; the family name has 19 bytes, and no 19-byte name is wider than 19 "W" (the widest letter per byte),
  which fits the screen.
* Names inside sentences drawn by the word wrapper 0x409D70 (event pop-ups and e-mails, 0x419E43, 0x41ACxx,
  0x41AE92): the wrapper breaks lines at spaces, its lines (0x1B0 = 432 pixels for the event dialog) are wider than
  any 24-byte name (at most 24 "W", 384 pixels in SegoeUiBold18; a short form's whole name is fitted into the same).
* The other screens' status lines (labels made for three spaces, centred on x = 400 at y = 572: 0x4359E7, 0x437844,
  0x44A636; SetText 0x436378, 0x43731E, 0x43814E): they have the whole screen width.
* Every other text draw in the exe (all 69 calls of 0x409CC0 / 0x409CD0 / 0x409D20 / 0x409D70 and the 12 of
  0x402320 were read): button captions, achievements, dialogs, the store, the debug tools; none draws a name.
  Every read of a name field (villager +0x2A44, the family name gs+0x1B12C, the slot names gs+0x1B192 + 0x15 k,
  the Family Tree's records) was followed to its use: the tree, the labels and boxes above, sprintf into sentences
  ("{name}" through 0x44FDD0, 0x44E9B0, "Approx. daily income from %s: $" 0x415932), the save and the log.

### Proved (tests)

`tests/test_name_fit.py`, the REAL vf1text.dll and vf1font.dll on the REAL exe in Unicorn, their GDI calls made by
this machine's real GDI: the Family Tree screen's layout is the game's own (its constructor and draw 0x43A1B0 run
in `tests/ui_emu.py`, giving each name's place and each frame's), and each name is drawn through the game's own
call instruction at 0x439C74, 0x439DB3 and 0x439F49; the bottom bar's labels are made by the game's own constructor
calls, given their text by the game's own SetText calls and drawn by 0x40D140. Five Cuneiform signs, eight Japanese
letters and 24 "W" are drawn inside each frame (fitted with "…" wherever they are wider than the room: every child's
frame; 24 W everywhere), ordinary names (Emma, Jack, Sophia, Christopher) exactly as the stock draw places them, a
short form on the tree as its whole name fitted to the frame, a single-byte name with the byte 0x85, letters with
marks, emoji with skin tones, flags and joined emoji never cut, trailing spaces dropped; a label given a name by any
other SetText call draws it whole, as the stock game does, and the bottom bar's activity label, made for "Fishing"
(0x444914), shows a longer text whole. On the previous code 22 of its 47 checks fail.

### Live checks (not yet done)

1. A family member named with five U+1208D (or 𒂍𒂍𒂍𒂍𒂍), a child named 山田花子太郎次郎 and one named with 24 "W": the
   Family Tree screen shows each child's name inside its frame, ending in "…"; the parents' names stay inside the
   parent frame; select each in the house: the bottom bar's name stops before "Age".
2. The status line with two long names ("WWW… sees WWW….") stays inside its box.
3. An ordinary family (names like Emma, Christopher): the Family Tree screen and the bottom bar look exactly as in
   the stock game.
4. The Details screen, the dating screen and the adoption screen: every value (career, likes, money) shows whole, as
   in the stock game (the label fault above).
5. Use Unicode Font with Comic Sans MS: the same checks.

## Not in this part (the rest of the stage-3 work)

* Colour emoji (GDI draws them in one colour; DirectWrite would be needed).
* CJK line breaking (the game's word wrapper only breaks at spaces).
* Right-to-left and shaped scripts (Arabic, Hebrew order, Indic shaping) are drawn one character at a time,
  unshaped.
* Translations, the Translations window and Share on GitHub.
