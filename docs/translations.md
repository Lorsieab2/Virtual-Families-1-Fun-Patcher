# Translations

Play Virtual Families 1 in your own language, or make a translation for everyone. The file format is the one every
patcher of this family uses (the Virtual Villagers Fun Patcher's `docs/translation-file-format.md`, version 1, commit
7f3624bb), so a translator learns it once. The window, the format code and the sharing are ported from the Fish and
Plant Tycoon Fix Patcher.

## Playing in another language

1. Patch the game with the **Translations** setting on (it is on by default; it installs `vf1tr.dll`).
2. Tools tab, **Translations...**: choose the language in **Language in the game** (each language is listed by its
   own name: Français, Deutsch, 日本語...).
3. Start the game. The choice applies from the next game start; there is no need to patch again.

**English (original)** leaves the game exactly as it is. A line the translation lacks, or a line it got wrong, stays in
English; the game never stops because of a translation. The patcher writes the choice into every modded copy of the
game it knows (the folders on the main tab): `<copy>\Virtual Families 1 Patcher Files\Translation.ini` and a copy of
the file, `Translation.txt`, beside it. `Translations.log` there says what the game used (line numbers of any line that
shows English, never the text).

Translations that came with the patcher (accepted on GitHub) are in its `translations\vf1` folder and are listed with
their translator's credit name. Yours are in `translations` itself.

## Making a translation

Tools tab, **Translations...**, **Make a translation**: choose the language (or **Other language...** with its own name
and code) and press **Make a translation...**. The patcher reads the English lines from your original game (it never
changes it), writes `translations\Virtual Families - <Language>.txt` and opens the built-in editor:

- the English on the left, your translation on the right; **Search**; **Show untranslated only**; how much is done, in
  lines and percent;
- the line's notes: the game's name for it, its placeholders, and its limit when the game keeps it in a fixed space;
- placeholders (`{name}`, `%d`) in colour in both texts, **Insert** buttons for them (and for `{il/elle}`), and a
  message as soon as one is missing or wrong: such a line shows English in the game;
- a preview in the game's own font (Segoe UI Bold 18, drawn as the game draws it, with `{name}` as "Zoë"), with a
  warning when the line is much wider than the English;
- it saves by itself; if the game uses this translation, its copy in the game folders follows.

The file is plain UTF-8 text, so Notepad works too, and so does a spreadsheet (open it as tab-separated text, save it as
tab-separated text or "Unicode Text").

**Add translation file...** (or drag a `.txt` file onto the window) checks a file you were sent and adds it; **Check**
shows coverage, errors and warnings with line numbers.

The list of translations takes several at once: click one, Ctrl+click to add or remove one, Shift+click for a range,
Ctrl+A or **Select All** for everything. Selecting never changes the game's language; only "Language in the game" at
the top does. **Export...** saves a copy of each selected translation (one file each; several go into a folder you
choose). **Delete...** asks one Yes/No question listing the files (No is the default and does nothing) and moves them
to the Windows Recycle Bin (`SHFileOperationW` with `FOF_ALLOWUNDO`), so you can restore them; if the Recycle Bin
refuses, nothing is deleted. "English (original)" is part of the game and is never deleted. A translation that came
with the patcher comes back with the next patcher update. Deleting the language the game uses puts the game back in
English from its next start, exactly as choosing English does.

After a patcher update, open your file in the editor: new lines appear untranslated, a line whose English changed is
marked "English changed" and comes back untranslated with your old translation kept beside it, and everything else
keeps working.

## The file

```
# Virtual Families - Français translation (format 1).
Key	English	Translation	Notes
@format	1	1
@game	Virtual Families
@language	English	Français
@code	en	fr
@translator		Your credit name
strings/1050~11a6767d	Done	Terminé	eSayDone
strings/679~b3b0dc0a	{name} finally got a promotion! {He/She} worked so hard for it. 	{name} a enfin eu une promotion ! {Il/Elle} a tant travaillé pour l'avoir. 	eString_partnerPromotionMessage3; the game fills {name}
```

- Columns are separated by tabs: **Key**, **English**, **Translation**, **Notes**. Never change the Key or the English:
  the key holds the English's fingerprint (`strings/<id>~<first 8 hex digits of its SHA-256>`), and a line whose
  English no longer matches shows English.
- `\n` is a line break, `\t` a tab, `\\` a backslash. Spaces at the start or end count.
- `strings/<id>` lines are the game's own string table (about 1,630 lines: menus, buttons, emails, random events, tips).
- `#` starts a comment. The file is saved as UTF-8 with a byte-order mark.

### Placeholders

- **Names and numbers the game fills:** `{name}` and `{name2}` are family members' names, `{award}` a number. Keep each
  one; any order.
- **printf conversions** (`%d`): keep the same ones in the same order. Write `%%` for a percent sign.
- `{{` and `}}` are literal braces.

### Choosing words by person

In a line the game fills with a name (its English has `{name}`, `{He/She}`...), the game itself chooses by the person's
sex: `{he/she}` takes the first word for a male and the second for a female (`{his/2/her}` looks at the second person,
`{name2}`). Write the same in your language, as many times as your grammar needs:

```
{name} a enfin eu une promotion ! {Il/Elle} a tant travaillé pour l'avoir.
{name} est {name: m=content | f=contente}.       (the format's own form: the game gets {content/contente})
```

Neither part may hold `/`, `{` or `}` (the game splits at `/`). A line the game does not fill (no `{...}` in its
English) cannot choose by person: it would show the braces.

### Choosing words by number

`{award: one=pièce | other=pièces}` and `{%1: one=... | other=...}` are part of the format: the keys are your language's
CLDR plural categories (`zero`, `one`, `two`, `few`, `many`, `other`) and exact values (`=0`, `=1`...). The game never
hands the count to a line, so in Virtual Families such a choice always shows its `other` form; the editor and the
validator still check it.

### Limits

Some lines are copied by the game into a fixed space. Their notes say "at most N letters" (an accented letter counts 2,
a non-Latin one 2 or 3); a longer translation shows English, so it can never overflow:

- lines the game copies with `strncpy` into a fixed field (the villagers' action captions, 39 bytes): that field less
  its end;
- lines it formats with `sprintf`, adds with `strncat` or copies byte by byte into a buffer: at most as long as the
  English;
- every line: at most 1,000.

`tools/build_vf1_translation_limits.py` finds these places in the vanilla code (data/vf1_translation_limits.json). Eight
copies take a line chosen by data (an item, an event, a caller's table) rather than by the code: vf1tr.dll redirects each
of those calls through a guard that hands the copy a translated line cut to its English length, so those copies never
hold more than in the English game.

**Never translated:** the words the Family History log writes and the Family Tree Maker reads back ("Male", "Female",
"New Generation", "Nursing", the causes of death, the college title), the likes and dislikes lists (the game picks
their items by position) and the decimal point.

### Letters

The game draws bytes with its own fonts. Without the Unicode settings a translation is shown in Windows-1252: Latin-1
(French, German, Spanish, Portuguese, Italian, Dutch, Nordic...) plus the usual quotes and dashes; any other letter
shows as `?`. The editor warns about such letters. With **Render Unicode with In-Game Fonts** or **Use Unicode Font**,
vf1tr.dll passes the text on as UTF-8, which they draw, so Turkish, Polish, Russian, Japanese, Chinese... appear.

### Not translated

The patcher's own windows and the Upgrades pages of vf1fun.dll are not part of the file; names the player types, and the
game's pictures (with their words), stay as they are.

## The patches' own text

Everything a patch adds that a player can see is in the template too, after the game's own lines: the Upgrades button
and menu, every page of it (Cheat Upgrades, Villager Cheats, Store, House and Yard, Time Controls, Special Upgrades,
Services, Family, Clothing and Hairstyles, Flea Market, Patcher Achievements), every message and question, the
achievements and services, and the Behavior Label Variants captions under a villager. Their keys start with `patch/`
(for example `patch/vf1fun.no_money~...`); a line you leave empty shows its English. Each has its room: a caption the
game draws under a villager at most 39 letters, a window's text three times its English (at least 80, at most 600).

The Family History log's words ("Male", "Female", the causes of death, "New Generation", "Nursing"...) are translated
in the game; the log file itself stays in English, because the Family Tree Maker reads it back. The likes and dislikes
lists can be translated item by item: keep every item, in order, separated by commas, each no longer than its English
(the game picks an item by counting commas). Only the decimal point is never translated.

Any Unicode character can be used (the whole Unicode 18.0 chart collection and anything later): the patcher never
rejects a letter because it does not know it. Whether the game can draw it depends on the Unicode settings and fonts.

## Sharing

The Translations window says: "If you want to share your translation, consider going to the Patcher's GitHub page and
adding it!" -- How: press **Share on GitHub...**, drag the file in, press **Submit**.

Share on GitHub... first asks whether you want to continue (No is the default and changes nothing), then asks for the
**credit name** you want shown with the translation: you type it every time, it is public, and the patcher never fills
it in (not from git, Windows, GitHub or a save). **Email addresses are never saved and are rejected from translation
files.** Then the patcher writes a copy with that credit into `translations\Shared`, shows it in its folder and opens
GitHub's translation form with the game and language filled in: drag the file into the form and press Submit.

You need a free GitHub account: https://github.com/signup

When the owner accepts it (the `accept-translation` label), a GitHub Action downloads the file, checks it as data only
with the patcher's own validator, and opens a pull request adding it to `patcher/translations/vf1/`, committed by the
bot (github-actions[bot]) and credited only to the typed credit name; if something is wrong it comments the problems
instead. Accepted translations ship in the next release and appear in every player's language list.

A "(TEST)" translation (its file name, language name or credit says "(TEST)") is for trying out only: it lives in
the repository's `translations/` folder and never ships in a release (`tools/package_release.py` leaves it out;
`tests/test_release.py` checks it). `translations/fr.tsv`, "(TEST) - French AI Translation" credited to "(TEST) AI
translation", is one: an AI translation of every line, game and patch, to install with **Add translation file...**.

## For developers

- `patcher/translation_format.py`: the format (reading, writing, placeholders, person and number choices, CLDR plural
  rules, email refusal naming the line, coverage). Pure Python, no game or GUI imports: the Action runs it on a
  submitted file as data only.
- `patcher/vf1_translation_strings.py`: every line a translation can replace, with its room; read from the player's own
  executable (the patcher never ships the game's text).
- `patcher/vf1_translations.py`, `patcher/vf1_translations_window.py`: the files, the choice, sharing; the window and the
  editor (drag and drop through WM_DROPFILES).
- `native/vf1tr` builds `vf1tr.dll` (`native/build_tr.bat`). vf1fun.dll loads it last (after vf1text.dll / vf1font.dll)
  and calls `VF1Tr_Startup`. **No code hook on the lookup:** the game's static string records `{id, key*, text*,
  override*}` (from 0x4F5618) have an override pointer that theStringManager::GetString 0x44FD90 and the template filler
  GetStringFromNameGenderTemplate 0x44FDD0 already return when set (the game's own localisation hook, fed by an
  `sm.xml` the game does not ship). vf1tr.dll sets the override of each translated line, so every DLL that calls or
  pins the lookup (vf1fun, vf1logs) sees its code unchanged. The only code it changes are the eight guarded `call`
  instructions (0x41AE55, 0x4374F9, 0x4491BC, 0x4492F9, 0x44E8E3, 0x46EE9D, 0x4797D2, 0x47A513), each chained to whatever
  that call reached before. It writes all of it or nothing.
- `tools/build_vf1_translation_limits.py` writes `data/vf1_translation_limits.json` and `native/vf1tr/vf1tr_limits.h`.
- The patches' own text: every visible literal in `native/vf1fun` is marked with `TR`, `TR_N`, `TR_A` or `TR_NA`
  (`native/vf1fun/translate.inc`); `tools/vf1_patch_text.py` writes `data/vf1_patch_strings.json`, which
  `vf1_translation_strings.patch_entries` adds to the template. At run time vf1fun.dll asks `VF1Tr_TextW` /
  `VF1Tr_TextA` for a line by its English; vf1logs.dll asks `VF1Tr_English` / `VF1Tr_EnglishOf` so the log stays in
  English. `tests/test_patch_text_coverage.py` fails on any visible literal that is not marked, on a DLL that shows
  text without being listed, on a stale JSON, and on a dialog or buffer a translation could overrun.
- `scripts/accept_translation.py` is the Action's check; `.github/ISSUE_TEMPLATE/translation.yml` the form.
- Tests: `tests/test_translation_format.py`, `tests/test_translations_runtime.py` (the DLL in Unicorn against the real
  game's GetString, template filler and guarded calls), `tests/test_translations_window.py`,
  `tests/test_translation_sharing.py`, `tests/test_patch_text_coverage.py`.
