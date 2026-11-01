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
| +4 | SegoeUiBold17 | Images\SegoeUiBold17.png | 0x4EC610 | 17 |
| +8 | SegoeUiBold24 | Images\SegoeUiBold24.png | 0x4EE460 | 24 |
| +0xC | SegoeUi33 | Images\SegoeUi33.png | 0x4EB6F0 | 33 |

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
fixed bytes in the save (family name 19, slot menu 20, a person's name 24, parents' names 25), and in this first
part the limit is those bytes, so an accented letter takes 2 of them and a Chinese letter 3: the one shared
character limit with the full text in a sidecar is the next part (below).

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

## Not in this part (the rest of the stage-3 work)

* One shared character limit, counted in characters, as large as possible, with the full text in a per-save
  sidecar and the game's name boxes and drawing patched to use it.
* Colour emoji (GDI draws them in one colour; DirectWrite would be needed).
* CJK line breaking (the game's word wrapper only breaks at spaces).
* Right-to-left and shaped scripts (Arabic, Hebrew order, Indic shaping) are drawn one character at a time,
  unshaped.
* vf1fun.dll's own Windows dialogs (Spawn Child's name, the Family page) still use the system code page for names.
* Translations, the Translations window and Share on GitHub.
