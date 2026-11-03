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
measure-only flag; the justified word wrapper (0x409D70, 0x409DA9..0x40A0B9) splits text at spaces and measures each word
with it (see "Line breaking for every script" below for its whole algorithm). `tests/test_vf1_game_fonts.py` runs these on every font and compares every box, place, width and pixel
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
| 0x40DA70 text box handler | the stock rules, plus whole code points (posted as 0x40000000 + code point) added by the write rule (below) when they fit, and Backspace deleting a whole character |
| 0x4049BB SDL_TEXTINPUT | one byte goes on as before; longer text is posted a character at a time |
| 0x40DA70 text box handler, typing | a mark typed right after a refused character belongs to it and is refused too (it never lands on the box's last character; a character after a refused joiner is refused as well); in a box that is not a name box, a character that would make the text wider than its byte limit times the widest plain letter of its font is refused (a name box scrolls instead) |

**Storage in the game's own fields: a Windows-1252 letter is one byte, any other letter UTF-8** (the shared Unicode
spec's per-character write rule and per-sequence read rule, the Virtual Villagers patcher's). ASCII is unchanged. *Write,
per character:* a character Windows-1252 has is stored as its one byte, any other character as UTF-8, in the same
string, inside the same byte field, which is never made bigger; "Zoë 日本" keeps a stock-readable ë beside the Japanese
and an old Latin-1 name keeps its bytes. If the mixed bytes would read back as different text (a Windows-1252 "Ã"
followed by "©" spells the UTF-8 sequence of "é"), every non-ASCII character of that string is stored as UTF-8.
*Read, per sequence:* each well-formed UTF-8 sequence (shortest form, no surrogate, nothing past U+10FFFF) is its
character, and every other byte is read one byte per character (Windows-1252; its five unassigned bytes as Latin-1).
So an old or hand-edited save reads as before, a name every earlier version stored (pure UTF-8) reads as it always
did, and a mixed string reads right. The one change from the earlier whole-string reading is a string that is not
valid UTF-8 as a whole but holds a valid sequence (for example the bytes of "Zoë" followed by the two bytes of "é"):
it now reads its sequence as that letter instead of two Latin-1 letters. A box holds its text in this stored form, so
its 1,200 bytes are bytes as stored: a character is added by the rule (the whole text is stored again when a neighbour's
form must change), and Backspace stores the rest again. A name is cut only between whole characters (grapheme
clusters: a letter with its marks, emoji with skin tones, joiners and variation selectors, a flag's two letters, and
CR LF as one character, the shared Unicode spec's rule and the Virtual Families 2 patcher's; a joiner never takes a
line break after it). The draw and measure loops still take CR and then LF (`DrawEnd`, `vf1_text.clusters(draw=True)`),
so text with line breaks is drawn exactly as before (`tests/test_cluster_crlf.py`).
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
   font): the first face of the shared Unicode spec's chain (2026-11-03) whose character map has every character
   of it: Segoe UI, Segoe UI Historic, Segoe UI Symbol, Segoe UI Emoji, Yu Gothic, Meiryo, Microsoft YaHei,
   Microsoft JhengHei, Malgun Gothic, SimSun-ExtB, Nirmala UI, Ebrima, Gadugi, Leelawadee UI, Myanmar Text,
   Javanese Text, Mongolian Baiti, Microsoft Himalaya, Microsoft Yi Baiti, Microsoft New Tai Lue, Microsoft Tai Le,
   Microsoft PhagsPa, Sylfaen, Cambria Math, Noto Sans, Noto Sans Symbols, Noto Sans Symbols 2, Noto Sans CJK JP,
   Noto Sans CJK SC, Noto Sans Math, Noto Sans Cuneiform, Noto Color Emoji (a face not installed is skipped;
   `FallbackFaces[]` = `vf1_glyph_gdi.FALLBACK_FACES`); when that face is a colour font, the letter is drawn in
   colour ("Colour emoji" below);
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
Owner's Defaults keeps Render Unicode with In-Game Fonts too; Patch Selection Settings refuses ticking both at once; the command line
refuses `--enable` of both and lets `--enable` of one turn the other off.

Proved: `tests/test_unicode_font.py` runs the game's DrawString and GetWidth with the real vf1font.dll in Unicorn,
its GDI calls made by real GDI, for Segoe UI, Comic Sans MS and Arial loaded from a font file, in all four fonts:
every place, box and pixel equals the patcher's preview.

Live check: tick Use Unicode Font, patch, pick Comic Sans MS with Unicode Font..., start the game: every screen's
text is in Comic Sans, buttons and dialogs still fit, a typed accent and a Japanese name show; pick a font file and
start again.

## Names in vf1fun.dll's own windows

The Upgrades menu's windows (the Family page, Spawn Child, Adopt Outside Child, Villager Cheats, Clothing and
Hairstyles, Services) read every name by the same one rule (`native/vf1fun/text_names.inc`: per sequence, UTF-8 or one byte
per character, Windows-1252) and store a typed name by the write rule in the 24 bytes the game gives it, cut only between
whole characters (the same cluster table, `native/vf1text/extenders.inc`); control characters and unpaired
surrogates are never stored. Before, they used the system code page, so a name like "日本" could become
"??". This holds whichever of the two Unicode settings is on, or neither (the stock game then shows each UTF-8 byte as a
Latin-1 letter, as for any such name; a Windows-1252 letter it shows as itself). `tests/test_vf1fun_names.py` runs the DLL's own code for both rules in
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
  the AND; the stock game draws such names, UTF-8 bytes as Latin-1 letters, without harm.
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
9. Characters above U+FFFF typed into the game's own name boxes (section "Fixes from the first live test"): with
   the Windows emoji panel (Win+.) and with a tool that sends KEYEVENTF_UNICODE (💩, 𒂍, 👍🏽): each appears whole and
   Backspace removes it whole; é and 日 still type as before.
10. Details screen: open and close it (and switch between members) for a member whose stored name is 19..24 bytes
    (Spawn Child with 23 letters; Spawn outside child with 𒂍𒂍𒂍𒂍𒂍) and for one with a long name in the Names file:
    the Family Tree still shows every sign, and the save's name field is unchanged (Copy Player Slot / the save
    reader show the same bytes). Then rename the member: the new name is stored.
11. Copy and Paste in Text Boxes (below): in each of the game's name boxes, Ctrl+V and Shift+Insert paste (a long
    name stops at 1,200 bytes; a copied line break becomes a space), Ctrl+C / Ctrl+Insert copy the whole name into
    Notepad, Ctrl+X empties the box; with both Unicode settings off, a pasted "Zoë 日本" gives "Zoë "; the keys do
    nothing in the house, the store or the Family Tree with no box being typed into (Insert keeps its stock use).

## Fixes from the first live test (2026-11-01)

The first live test used a build with typing and drawing but before the one character limit (#54, #55, #57).

**Characters above U+FFFF were dropped when typed (VERIFIED, emulated with the game's own SDL2.dll).** The game's
SDL2.dll is 2.0.3. Its window procedure (0x100EBF40) makes typed text in WM_KEYDOWN (0x100EC509): `ToUnicode` gives
one UTF-16 unit, and SDL writes that unit by itself as UTF-8 by hand (0x100EC5B1..0x100EC6D4) before
`SDL_SendKeyboardText` (0x100B0380). WM_CHAR is ignored (0x100EC7AF only sets the return value); WM_UNICHAR is not
handled; an input method's composed text comes from WM_IME_COMPOSITION as whole UTF-8. So a character above U+FFFF
sent as a VK_PACKET pair (SendInput KEYEVENTF_UNICODE, the emoji panel) arrives as two SDL_TEXTINPUT events, each a
lone surrogate written as three bytes ("ED A0..AF xx", then "ED B0..BF xx"). Neither is UTF-8, so vf1text.dll's
SDL_TEXTINPUT detour skipped both. é and 日 are one unit each, so they typed. Fix (`PostTypedText`, both DLLs): a
high half waits for the next event; a low half right after it makes the whole code point, posted as any other; a
lone half, or one followed by anything else (the one-byte path clears it too), is never typed.
`tests/sdl_emu.py` runs the REAL SDL2.dll in Unicorn (its own SDL_InitSubSystem, SDL_StartTextInput, window
procedure and SDL_PeepEvents; only ToUnicode's answer and the kernel32 calls are stood in for), and
`tests/test_vf1_unicode_text.py` feeds what it makes through the game's own event-loop case into the box.

**Opening the Details screen cut a stored name (VERIFIED, emulated).** The rename box opens with the member's field
(SetText from 0x44BC78, villager + 0x2A44, which holds up to 24 bytes: Spawn Child and Adopt Outside Child store 24),
but the game reads it back into a 20-byte local with GetText(local, 0x13) at 0x44BCE1 / 0x44BDDE and copies that over
the field and the Family Tree's copy (ChangeName 0x481C20) whether or not the name was changed. A 20-byte name of
five Cuneiform signs became 16 bytes (four signs); with the one limit it would have become a short form and a
Names-file line. Fix (`names.inc`): the DLL notes what a name box opened with (SetText / SetEditable); at those two
GetText sites a box still holding exactly that text gives "" -- the game then skips both copies (0x44BCE6 / 0x44BDE3:
`cmp byte [esp+8], 0; je`), so the field, the Family Tree and the Names file stay byte for byte as they were. A
changed name is stored as before. The other boxes' GetText rooms already equal their fields (the slot menu and the
first family: 19 of 20; adoption and a new baby: new names). `tests/test_name_limit.py` runs the game's own open
(0x44BC56..0x44BC7D) and both closes with a 23-letter name, 24 "W", five Cuneiform signs, eight Japanese letters and
sidecar long names, draws the box in between, and checks the whole member record, ChangeName and the Names files;
and every other name box with a full-size name, a full-size Cuneiform name and a sidecar name.

**Names wider than their spot**: see "Names fitted to their spot" below (#63). **vf1fun's windows** (the Family
page's missing buttons, Cuneiform boxes): see "Names in vf1fun.dll's own windows" above (#62).

## Copy and Paste in Text Boxes (`CopyPasteInTextBoxes`, on by default)

`native/vf1fun/clipboard.inc`, in vf1fun.dll, so it works with either Unicode setting or neither. While one of the
game's own text boxes has the typing cursor: Ctrl+V or Shift+Insert pastes the clipboard's CF_UNICODETEXT at the end
of the box (a game box's caret is always at the end); Ctrl+C or Ctrl+Insert copies the box's whole text (a name box
holds the whole name, never its short form); Ctrl+X copies it and empties the box. No Alt (AltGr letters are left
alone).

**How (VERIFIED in the exe).** ldwGame's event loop reads SDL_KEYDOWN's key code and modifiers at 0x404826 and
switches on the code; V, C and X do nothing there, Insert posts (6, 0x3F4). SDL makes no SDL_TEXTINPUT while Ctrl is
held (ToUnicode gives a control character, which SDL_SendKeyboardText drops), so the stock game never types a v, c
or x for these keys (`tests/test_clipboard.py` runs it in the real SDL2.dll). Every message goes through the message
manager (0x402140 -> 0x401DA0), which asks its listeners in order; a text box (ldwTextControlImpl, vtable 0x4B2950)
takes typing while +0x25 (being edited) is set and its owner (+0x1C) is shown (+8). The patch jumps from 0x404826
(10 stock bytes checked first): for these keys it looks for that box among the listeners; with one, the key is used
and goes no further; with none, it goes on exactly as before.

**Paste rules.** CR LF becomes ONE space, and a lone CR, LF or Tab one space each; the text is composed (NFC, FoldStringW
MAP_PRECOMPOSED: "e" + U+0308 pastes as "ë") with a Unicode setting on as well as with both off; other control characters and unpaired surrogates are dropped;
a numbers-only box keeps digits (and a first '-', as the stock box allows). With vf1text.dll or vf1font.dll installed
(asked of the DLL: `VF1Text_UnicodeTextActive`, nonzero only once all ten hooks are in, not merely that the file is
loaded) the text is stored by the write rule, cut between whole characters at the box's limit (a name box 1,200 bytes with no character cap,
any other box its own bytes); a pasted mark that would join the box's last letter and no longer fit is not pasted.
With both off, only characters the stock fonts can store and draw are kept, one byte each (U+0020..U+007E and
U+00A2..U+00FF, after composing accents with FoldStringW MAP_PRECOMPOSED), up to the box's own byte limit. (Owner,
2026-11-03: "what the fonts draw". The set is the glyph tables of the four stock fonts, read from the exe by
`tests/test_clipboard.py::test_the_set_with_both_off_is_what_the_stock_fonts_draw`: 0x20..0x7F and 0xA2..0xFF in all four;
DEL is a control character and is never pasted. The stock box itself (0x40DB0F) is stricter, refusing every byte from
0x80, but the owner's rule is the fonts', so a Latin-1 letter pastes.) A held key's auto-repeats (SDL's repeat flag) are
swallowed while a box has the typing focus, so one press acts once; Ctrl+X empties the box only after the copy succeeded.
Nothing is ever
written past the box's buffer (limit + 1 bytes); the game is told the text changed (0xC, 0x401EA0) as after a typed
letter. (A Latin-1 name pasted with both settings off is read by the one rule as Windows-1252, except in the rare
case its bytes also form a valid UTF-8 sequence, such as "Ã©", which then reads as "é".)

**vf1fun's own windows** are standard edit boxes: Ctrl+C, Ctrl+V, Ctrl+X and the right-click menu are their own,
and nothing in vf1fun blocks them (#62).

**Proved** (`tests/test_clipboard.py`, the game's event loop from 0x404826, the real message manager walk and the
box's own HandleMessage, with the harness DLL built from vf1fun.cpp, in Unicorn; only the clipboard is stood in for):
pastes into a name box at 300 characters (no cap there), at 1,200 bytes and one past, joined emoji cut whole, CR/LF/Tab,
control characters and lone surrogates; into a box with text, at the byte limit and one past; other boxes' limits;
a numbers-only box; with both settings off (Latin-1, composed accents, dropped characters, the 20-byte limit and one
past); Shift+Insert; copy, Ctrl+Insert and cut; guard bytes after every buffer; no message reaches the game while a
box takes the key; with no box being typed into (or one on a hidden page) every key goes on exactly as in the stock
game; Ctrl+Alt+V, AltGr+V, Ctrl+Shift+V and Ctrl+B are left alone.

## One character limit for every name box (2026-11-01)

### Release note

> **Long names, everywhere.** With Render Unicode with In-Game Fonts or Use Unicode Font on, every name box takes
> names up to 1,200 bytes (up to 1,200 plain letters; fewer when letters need more bytes): the family name, the slot
> menu's New Player, adoption, a new baby, renaming a family member, and the Upgrades menu's Spawn Child and Adopt
> Outside Child; Rename Family and Copy Player Slot take the same. It is one limit, shared with the other Fun Patchers,
> with no separate character cap. Characters are counted as you see them
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

`NAME_BOX_BYTES = 1200` in `patcher/vf1_text.py` is the only place the number is written; the mark `"..."` sits beside
it. There is no separate character cap (the earlier 300-character `NAME_LETTERS` is gone, owner decision 2026-11-03: "All
games: up to 1,200"). `scripts/build_vf1_text_tables.py` writes both into
`native/vf1text/extenders.inc` (`VF1_NAME_BOX_BYTES`, `VF1_NAME_MARK`), which vf1text.dll,
vf1font.dll and vf1fun.dll include; `tests/test_name_limit.py` checks that nothing else spells the number.

The ceiling is the LDW engine's own: `ldwTextControlImpl::SetEditable` 0x40D370 clamps every box's limit to 0x4B0
= 1,200 bytes (`cmp edx, 0x4B0` / `mov edx, 0x4B0` at 0x40D3B3) and allocates limit + 1 bytes; Fish / Plant
Tycoon's engine has the same cap. A box takes a typed code point only while the text stays within 1,200 bytes, so it
holds up to 1,200 plain letters and fewer when letters need more bytes (one code point is at most 4 bytes of UTF-8:
buffers sized for characters are sized 4 x the characters, the worst-case box maths). The cap is not patched past.

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
through GetText, which now gives the game only the short form: at most `size - 1` bytes, stored by the write rule, never more
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
| 0x409D70 the word wrapper | whole names for short forms before the stock wrapping (and, since 2026-11-02, line breaks for every script: "Line breaking for every script" below) |

and the first part's hooks do more: HandleMessage counts a name box's bytes (1,200; there is no character cap);
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

**The Names file**: `<saves>\Virtual Families 1 Patcher Data\Names\Virtual Families<N>.ldw.txt`, UTF-8 text (the file's names are text, never the game's mixed bytes; the DLL converts) in lines
`VF1 Names 2`, then `short<TAB>room<TAB>whole name<TAB>CRC` (room: the field's bytes it was made for; CRC: the CRC-32
of everything before the last tab, 8 upper-case hex digits, as in the Virtual Villagers patcher). A record whose CRC
fails (cut short, merged with another, changed) is skipped. A `VF1 Names 1` file (no CRC column) is still read, and the
next write of it makes it version 2. Written through a temporary file and MoveFileEx. **Pending writes:** a record is
written at once, the moment a name leaves a box; when that cannot be done (the member's slot is not known yet, the game
state has no save path yet, the folder cannot be written) the record stays in memory, its book marked dirty, and every
draw retries, at most once in 2 seconds, until a write of that book has succeeded (a record made with no slot known is
kept in a pending book and moves to the slot's book, whose file is read first so nothing in it is lost, as soon as the
slot is known). The whole names it holds are shown meanwhile. After every save of slot 1..5 (vf1fun.dll's theGameState::Save hook) vf1fun.dll calls `VF1Text_FlushNames`, which writes every such record at once, without the 2-second wait, so a name stored just before the player saves and quits is in the file (never at DLL detach, when the game's objects may be gone). A line is never removed: a short form no longer in the save is harmless (a new one
is never made equal to it), and the older autosave copies `<N+20>` / `<N+40>` stay readable. A line that is not
valid (no mark, too long for its room, a control character, more than 1,200 bytes) is left out;
a file that cannot be read is read as empty, and the save shows its short forms.

**Who else reads it**: vf1logs.dll writes the whole name in the Family History log (`Text::Name` asks
vf1text.dll / vf1font.dll's `VF1Text_FullName`); vf1fun.dll's windows show whole names, and Spawn Child / Adopt
Outside Child take 1,200 bytes (`VF1Text_StoreName`, in the 24 bytes those windows use); the patcher's
`vf1_save.read_save`, the Family Tree Maker (`vf1_genealogy.load_village`, before the tree file and the log), the
Family History reader (an older log's short forms), Rename Family and Copy Player Slot (both write the Names file:
a long new name gets its line, the copy takes the source's file with the new name's line; a failed rename puts it
back) use `patcher/vf1_names.py`.

### Proved (tests)

`tests/test_name_limit.py`, with the REAL vf1text.dll and vf1font.dll on the REAL exe in Unicorn
(`tests/names_emu.py`): each of the ten boxes, set up from its own call site, takes 1,200 plain letters and refuses the
1,201st byte, and takes 300 four-byte characters (1,200 bytes) and nothing more, with guard bytes after every buffer the
game allocates; joined emoji stop at the 1,200-byte cap; combining marks count only as bytes; Backspace removes one whole
character; the three other boxes keep their stock limits; for every GetText site the game's own instructions run
from the call to the end of the copy after it, with names that fit exactly, one byte past the field, 300
characters, 300 accented characters, 1,200 plain characters and 1,200 bytes, and nothing outside each destination field or local buffer
changes (guard bytes) while the destination holds `vf1_names.short_form`'s answer and the Names file the whole
name; short forms of names that start alike are unique and equal the patcher's; the same name keeps its short
form; a rename box opens with the whole name; DrawString, GetWidth and the word wrapper show the fitted whole name
in all four fonts; a long name scrolls in its box and the box's text is never cut; the Names file is read again
after a restart; a damaged one reads as empty. `tests/test_rename_family.py` and `tests/test_copy_slot.py`: long
names, the Names file, two names that start alike, a failed rename undone.

### Live checks (not yet done)

1. New family with a name typed until the box stops (1,200 bytes): the box scrolls; the main screen, the slot
   menu and the Family Tree screen show the whole name (with "…" where it does not fit); quit and start again:
   the same.
2. Adopt, name a new baby and rename a member with a long name and with a very long Japanese name; open the
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
is drawn as its longest start of whole characters (grapheme clusters), trailing spaces dropped, then "…" (U+2026, as UTF-8), measured with the
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
  (A name in a script written without spaces may now also break between its letters: "Line breaking for every
  script" below.)
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

## Line breaking for every script (2026-11-02)

### Release note

> **Japanese, Chinese, Korean, Thai and emoji text now wraps.** With Render Unicode with In-Game Fonts or Use
> Unicode Font on, a sentence in a script written without spaces breaks onto the next line where the Unicode
> line-breaking rules allow (no line starts with 。、」 or a small kana; none ends with 「), never inside a
> character. Text in any other script is laid out exactly as before, pixel for pixel. A single word wider than the
> whole line, which made the stock game hang for good, is cut between characters instead.

### The stock wrapper (VERIFIED in the exe, run in the emulator)

`0x409D70` (text, x, y, width, colour, font, measure only; ret 0x1C; its frame is 0x4DC bytes) is the game's one
justified word wrapper (event pop-ups and e-mails, 0x419E43 with width 0x1B0 = 432, 0x41ACxx, 0x41AE92). It cuts the
text into "words" (0x409E95..0x409EE3): a run of bytes that stops at a space or a line break, and right after a "."
not followed by another ".", a "," not followed by a digit, or a "?". It fills a line with whole words, measuring
each with the counted draw 0x409450 (measure only); between two words lies the width of " " (0x4B27BC), stretched
to justify the line (free pixels / gaps each, the first `free mod gaps` gaps one more), unless a gap would pass 5/3
of a space while the line is emptier than the float at 0x4B27B8, or the line is the text's last and ends in "." or
"?". A line that does not fit (0x409F86) drops its last word to the next line, or, when the overrun is smaller than
the number of gaps, squeezes every gap by a pixel. At most 100 words a line (its arrays). A wrapped line drops the
spaces before its first word; spaces at the text's start or after a line break are kept.

Two faults: a script written without spaces (Japanese, Chinese, Korean syllables, Thai, Lao, Khmer, Myanmar, emoji)
is one long word, so it never wrapped and ran off the dialog; and a word wider than the whole line makes the stock
code loop for ever (it drops the line's only word and starts the same line again: `test_the_stock_code_loops_for_ever_on_a_word_wider_than_the_line`).

### The patch (`native/vf1text/wrap.inc`, `linebreak.inc`; both DLLs; `patcher/vf1_line_break.py` is the same rule)

The wrapper hook of the one name limit (0x409D70, whole names first) now ends in `WrapText`:

1. `BreaksFor`: the text is read by the one rule; if it has a letter of a script written without spaces (the CJK
   punctuation blocks, or ICU's line-break classes ID, SA, H2, H3, JL, JT, JV, CJ, EB, EM; without ICU the
   built-in table's ideographic class) or a zero width space, the places a word may be cut are found: only between
   whole characters (grapheme clusters), next to such a letter (or after U+200B), never next to a space or a line
   break, and only where UAX #14 allows -- `ubrk_open(UBRK_LINE)` of Windows' own `icu.dll` (System32, Windows 10
   1903 and later; it also knows the Thai, Lao, Khmer and Myanmar dictionary words), loaded with
   `LOAD_LIBRARY_SEARCH_SYSTEM32`; without it the built-in table (`linebreak.inc` = `FALLBACK_RANGES`: ideographic
   letters, closing marks that never start a line -- 。、」）, the small kana, ー, ゝ --, opening marks that never
   end one; `test_the_dlls_built_in_table_is_the_patchers`).
2. If there is no such letter and every word fits the line it starts (`StockWordsFit`), the game's own code runs,
   untouched: stock text is laid out exactly as before.
3. Else `OwnWrap`: the stock algorithm step for step (the same word cuts, measuring, gap arithmetic, justify rule,
   squeeze, 100-word limit, last-line rule), with one change: a word may also be cut at the places found, and its
   pieces follow each other with no space between them (only the gaps between words are stretched; a word's pieces
   are drawn as one). A piece wider than the whole line is cut after the longest start of whole characters that
   fits (`EmergencyCut`), at least one character.

**Word lists without ICU (`native/vf1text/wordlists.inc` = `vf1_line_break.dictionary_inside`).** On a Windows
without `icu.dll`, Thai, Lao, Khmer, Burmese, Chinese and Japanese runs are cut into words by longest match with the
shared ICU 77-1 word lists (unicode-audit `word-lists`, copied unchanged into `patcher/payload/WordLists` and
installed in `Unicode Text\Word Lists` / `Unicode Font\Word Lists` with `ICU-LICENSE.txt`), and the built-in table
may then break a line only between two words. A list is read the first time text of its script is wrapped (never
when icu.dll is there); a missing list leaves the built-in table's breaks. `tests/test_word_lists.py` checks every
file's SHA-256 and runs the real DLLs without icu.dll against the model.

The patcher's `vf1_line_break.wrap(font, text, x, y, width, justify ratio, patched=...)` is the same algorithm over
`vf1_game_fonts`' letters: `patched=False` is the stock code (the tests prove it against the stock code's own
layout) and `patched=True` the DLL's.

### Proved (`tests/test_line_break.py`, the REAL vf1text.dll and vf1font.dll on the REAL exe in Unicorn, real GDI and real ICU)

* Stock text exactly as before: five paragraphs (justified lines, line breaks, leading and repeated spaces, "...",
  "$1,250.00", "1,000,000", ending in "." or "?") at three widths in all four fonts, and every sentence the exe
  holds (more than 100 printable ASCII strings with a space, release-only) at the event dialog's width: every blit
  (the same source sheet, box and place: the same pixels) and the returned height equal the stock code's, drawing
  and measuring; and the patcher's model of the stock code gives the same places.
* Japanese (with 「」、。 and a small っ and ー), Chinese (with （）), Korean, Thai, emoji (skin tone, flag, a joined
  family) and mixed English-Japanese text, at 432 and 160 pixels in all four fonts, and with vf1font.dll: the DLL's
  layout equals the model's letter for letter and pixel for pixel; every piece is whole characters; no line starts
  with a closing mark; the lines fit; the text did wrap; Thai breaks between dictionary words (สวัสดี ครับ ผม), not
  letters; joined emoji are never cut at any width; without icu.dll the built-in table wraps the same as the
  model's table and no ICU call is made.
* A word wider than the line: the stock code hangs (the emulator's instruction limit), the patched one cuts it
  between whole characters, in every font, for ASCII, a long run of "W" inside a sentence and 60 "é".

### Live checks (not yet done)

1. Rename Family to a long Japanese sentence (日本語の文章です。「こんにちは」と言った。...) and trigger an event
   pop-up that names the family, or send an e-mail: the text wraps inside the dialog, no line starts with 。、」, and
   the English sentences around it look exactly as in the stock game.
2. The same with a 24-"W" name in a sentence: the dialog shows it (cut between letters where the line is too
   narrow) instead of freezing the game.
3. Use Unicode Font with Comic Sans MS: the same two checks.

## Colour emoji (2026-11-02)

### Release note

> **Emoji in colour.** With Render Unicode with In-Game Fonts or Use Unicode Font on, an emoji in a name or a
> sentence is drawn as the colour picture Windows shows for it (Segoe UI Emoji): a skin tone, a joined family (👨‍👩‍👧)
> or a keycap (1️⃣) is one picture, and any letter from a colour font (Noto Color Emoji when installed, an emoji
> newer than the patcher's list) is in its own colours too; a country flag shows as its two letters in the text's
> colour, as everywhere in Windows. The picture is the
> text's size, sits on its baseline and keeps its own colours whatever colour the text is drawn in (a see-through
> colour still makes it see-through). The Game Text tool previews the same pictures. Add `ColourEmoji=0` under
> `[UnicodeText]` in `Virtual Families 1 Patcher Files\settings.ini` to have emoji black and white as before, which
> is also what a Windows without Direct2D gets.

### Why they were black and white

GDI (`TextOutW`) draws every letter in one colour and knows nothing of a font's colour layers, so the chain drew
each emoji from the first face that had it (Segoe UI Symbol) as a white outline the game then tinted. Colour glyphs
(Segoe UI Emoji's COLR layers) are drawn only by DirectWrite through Direct2D (`D2D1_DRAW_TEXT_OPTIONS_ENABLE_COLOR_FONT`).

### The rule: which characters (`patcher/vf1_emoji.py` = `native/vf1text/emoji.inc`)

A whole character (grapheme cluster) is a colour emoji when nothing in it asks for text presentation (U+FE0E) and
a code point of it has Unicode's Emoji_Presentation property (an emoji shown as a picture by default: faces,
animals, regional indicators, skin tones), or it holds U+FE0F (emoji presentation asked for: ❤️ ☃️), a keycap U+20E3,
a skin tone U+1F3FB..U+1F3FF or a tag character U+E0020..U+E007F. So ❤ and ☃ alone, digits and letters stay
letters. `EMOJI_PRESENTATION_RANGES` is Unicode 15.1's property read from Windows 11's own `icu.dll`
(`u_hasBinaryProperty UCHAR_EMOJI_PRESENTATION`, `build_emoji_presentation`), fixed in the module;
`scripts/build_vf1_text_tables.py` writes `emoji.inc` from it (`tests/test_vf1_text.py` checks it is up to date,
`tests/test_colour_emoji.py` that it equals ICU's answer).

### The face, and any letter of a colour font (the shared Unicode spec, row 3; Fish and Plant Tycoon's rule)

`ColourFace` (glyph_color.inc) = `vf1_glyph_gdi.Renderer.colour_face_for`:

* a colour emoji (the rule above) is drawn from the first face of the chain that is a colour font and has every
  character of it: Segoe UI Emoji, then Noto Color Emoji when installed (a CBDT font); if none has it, Segoe UI
  Emoji (DirectWrite's own fallback then finds a face);
* any other character is drawn in colour when the face the chain picks for it is a colour font: a face with a COLR,
  CBDT, sbix or SVG table (`GdiFace.colour` / `_Face.colour`, from `GetFontData`). So an emoji newer than the
  Unicode 15.1 list that Segoe UI Emoji already has (for example U+1FA89 harp, Unicode 16) is a colour picture,
  and with Use Unicode Font set to a colour font its coloured letters keep their colours.

Either way the drawing is **kept only when it has colour**, Fish and Plant Tycoon's `raster_colour` test: some pixel
at least 16 opaque with a premultiplied B, G or R 16 below its alpha (white ink from the brush has B = G = R = A;
black, as in 🖤 or the black flag, counts as a colour). A letter a colour font draws only in the brush's white, a
country flag's two letters, is drawn by GDI instead and tinted by the game's colour as any letter.

### How a picture is made (`native/vf1text/glyph_color.inc` = `patcher/vf1_glyph_color.py`, both DLLs)

`VF1Text_ColourLetter(face, weight, em, baseline, height, text)`: DirectWrite lays the character out in that face
at the font's em (Use Unicode Font: the fitted em) and the regular weight (a picture is never emboldened),
no wrapping; Direct2D draws it with `ENABLE_COLOR_FONT` and grayscale anti-aliasing on a software DC render
target bound to a 32-bit top-down DIB the cell's height high, transparent, the layout's baseline on the font's
baseline row (y = baseline - the line's baseline), x = pad. Its box is the black-and-white letters' rule (from
min(pad, first inked column) to max(pad + advance, last inked column + 1), the advance the layout's width rounded);
its premultiplied pixels are made straight (colour x 255 / alpha). Direct2D draws every colour format Windows
knows this way (COLR/CPAL, and CBDT, sbix and SVG on Windows 10 1607 and later), the path Fish and Plant Tycoon's
`raster_colour` uses. `d2d1.dll` and `dwrite.dll` are loaded from
System32 once; `D2D1CreateFactory` / `DWriteCreateFactory` need no COM initialisation.

In the DLLs (`LetterFor`), such a character is kept under its own cache key (a leading 0x01 before its UTF-8, so a
shipped black-and-white letter of the same character is left alone) on a colour page of the font (`colourPages`,
1024 x 16 bands, up to 4): `TintedSheet` gives a colour page back untinted whatever the colour, so the game's
AND tint (0x402940's rule) never touches it, while a see-through colour still goes through BlitRectWithAlpha as
for any letter. When DirectWrite cannot draw it (no Direct2D, no Segoe UI Emoji, a failed step) the character is
drawn by GDI in black and white, as before, and kept under the same key. `settings.ini [UnicodeText] ColourEmoji=0`
(read once, `WantColour`) keeps every emoji black and white and the old keys.

The patcher's `vf1_game_fonts.GameFont.glyph` does the same in the same order (`colour_emoji`, on by default; a
`Glyph` whose `colour` is set keeps its colours through `paint`), so the Game Text tool's preview, its "letters:"
line and its picker ("colour emoji: Segoe UI Emoji") show what the game shows; its "Colour emoji" tick box previews
`ColourEmoji=0`.

### The same as the Virtual Villagers Fun Patcher

The Virtual Villagers Fun Patcher's in-game Unicode text and Picture Studio draw emoji in full colour from Segoe UI
Emoji's COLR/CPAL layers, untinted, one picture per ZWJ sequence, skin tone, keycap or tag sequence, at the line's
size (its `docs/picture-studio-text.md`, "Emoji, in full colour"). VF1 draws the same layers through DirectWrite and
Direct2D, as Fish and Plant Tycoon does, which the shared spec names the strongest form (it covers CBDT, sbix and
SVG too; VV's own COLR renderer is the spec's accepted equal for COLR fonts). **Flags:** Segoe UI Emoji has no
country-flag pictures, so the Virtual Villagers patcher shows a country flag as its two letters, and so does VF1
(both as Windows itself draws them), in the text's colour; a tag flag such as Scotland's is the font's plain black
flag in both.

### Proved (`tests/test_colour_emoji.py`)

* The rule: 😀, 👍🏽, 👨‍👩‍👧, 🇯🇵, 1️⃣, ❤️, ☃️ and the Scotland tag flag are colour emoji and one whole character each;
  A, é, 日, ❤, ☃, ☹, 1, 😀︎ (U+FE0E) and e + U+0301 are not; the DLLs' table equals the patcher's and ICU's.
* The DLL's own `VF1Text_ColourLetter` through 32-bit rundll32 gives, for each of those in all four fonts' styles,
  the same width, height and every R, G, B, A byte as `vf1_glyph_color.draw`, and the picture is in colour (not
  every inked pixel white); for 🇯🇵 both keep nothing (white letters only, no colour).
* A country flag in the game is drawn on the tinted pages in the text's colour (red text: every inked pixel red).
* A letter the list does not call an emoji whose chain face is a colour font (U+1FA89, Segoe UI Emoji) is a colour
  picture in the tool and in the game, pixel for pixel, untinted, in two fonts.
* The colour test is FP's (white ink, a faint pixel, black, a colour); the chain in `FallbackFaces[]` equals
  `vf1_glyph_gdi.FALLBACK_FACES` and the spec's list, in order.
* Size and baseline, in each of the four fonts: the colour picture's first and last inked rows are within 2 pixels
  of GDI's black-and-white Segoe UI Emoji glyph at the same em and baseline, and its width within 3.
* Text without a colour emoji (accents, Japanese, Korean, Thai, Greek, Cyrillic, Cuneiform, the text-style ❤ and
  ☃, combining marks) is drawn by the DLL with colour emoji on exactly as with `ColourEmoji=0`: every blit's kind,
  place, box and all four channels, in all four fonts, white, a colour and see-through, and the word wrapper's
  lines; no picture is asked for. Checked once more against origin/main's own vf1text.dll and vf1font.dll (Segoe
  UI and Comic Sans MS) built from main's source, in the same emulator: 14 such texts in 4 fonts and 3 colours
  plus the wrapper at 3 widths, every blit identical.
* The patcher's fonts: every such character is a "colour emoji" Glyph; white and a colour give the same picture
  pixels; a see-through colour thins it; the letters around it are the game's own; off, the black-and-white letter.
* In the game (the REAL vf1text.dll on the REAL exe in Unicorn, GDI by real GDI, `VF1Text_ColourLetter` by the
  machine's real Direct2D through `text_emu._colour_letter`): DrawString with a name holding all eight emoji and
  with ❤ beside ❤️, in white and in a colour, in all four fonts: every blit's place, box and all four channels equal
  the tool's layout; GetWidth equals the tool's; a see-through colour goes through the alpha blit; a picture is made
  once and kept; the word wrapper and the counted draw use the same pictures; with `ColourEmoji=0` the emoji are
  black and white (GDI drew them, no colour call); without Direct2D the same; vf1font.dll draws them in colour at
  its fitted em.

### Live checks (not yet done)

1. Name a family member "Mia 😀👍🏽👨‍👩‍👧" and the family "❤️ Smith 🇯🇵": the house's bottom bar, the Family Tree
   screen, the slot menu and an event pop-up show the emoji in colour, at the text's size, not tinted (the store's
   coloured prices, the dialogs' dark text); ❤ without U+FE0F stays a plain heart.
2. Add `[UnicodeText]` / `ColourEmoji=0` to `Virtual Families 1 Patcher Files\settings.ini`, start the game: the
   same emoji are black and white as before.
3. Use Unicode Font with Comic Sans MS: the emoji are still Segoe UI Emoji pictures at Comic Sans' fitted size.
4. With Noto Color Emoji installed (a CBDT font), an emoji Segoe UI Emoji lacks is drawn from it in colour; with
   red or dark text, "🇯🇵" shows "JP"-style letters in the text's colour, not white.
4. Frame rate in the house with several emoji names on screen (each picture is made once).

## Not in this part (the rest of the stage-3 work)

* Right-to-left and shaped scripts (Arabic, Hebrew order, Indic shaping) are drawn one character at a time,
  unshaped.
* Translations, the Translations window and Share on GitHub.
