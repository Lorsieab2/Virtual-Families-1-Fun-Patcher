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

Translations that came with the patcher (accepted on GitHub) and the ones you download with **Download from
GitHub...** are in its `translations\vf1` folder and are listed with their translator's credit name. Yours are in
`translations` itself.

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
with the patcher comes back with the next patcher update, and any translation on GitHub can be downloaded again with
**Download from GitHub...**. Deleting the language the game uses puts the game back in
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
- **printf conversions** (`%d`): keep the same ones in the same order.
- **Percent signs:** only the placeholders the line's English has count as placeholders. Any other `%` is plain text,
  so write a percent sign as you normally would: `2 %`, `2 %` (no-break space), `50 % de réduction`. Where the
  game or a patch formats the line with printf, the patcher hands it each such `%` as `%%`, so it shows one `%`
  (the extra byte counts toward the line's room); anywhere else it is shown as you wrote it. `%%` shows as two
  percent signs unless the English has `%%` itself.
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

The patcher program's own windows are not part of the file (the Upgrades menu and pages in the game are: below); names the player types, and the
game's pictures (with their words), stay as they are.

## The patches' own text

Everything a patch adds that a player can see is in the template too, after the game's own lines: the Upgrades button
and menu, every page of it (Cheat Upgrades, Villager Cheats, Store, House and Yard, Time Controls, Special Upgrades,
Services, Family, Clothing and Hairstyles, Flea Market, Patcher Achievements), every message and question, the
achievements and services, and the Behavior Label Variants captions under a villager. Their keys start with `patch/`
(for example `patch/vf1fun.no_money~...`); a line you leave empty shows its English. Each has its room: a caption the
game draws under a villager at most 39 letters, a window's text three times its English (at least 80, at most 600).

Each of these lines is shown through its own key, never as a copy of a game line: a page's title and controls, the
lists, the descriptions, every message and question, the captions and the Upgrades button are translated where
they are shown; a game line that appears in a patch window (an item's name in the Flea Market) is the game's own line,
translated by its own key and shown as the same characters the game draws. `tests/test_patch_text_sentinel.py`
translates every patch line to a numbered sentinel and follows it to the page, list, message, caption or button
(the real vf1tr.dll for every key, and vf1fun.dll's own code with the game's own caption call sites in Unicorn).

The Family History log's words ("Male", "Female", the causes of death, "New Generation", "Nursing"...) are translated
in the game; the log file itself stays in English, because the Family Tree Maker reads it back. The likes and dislikes
lists can be translated item by item: keep every item, in order, separated by commas, each no longer than its English
(the game picks an item by counting commas). Only the decimal point is never translated.

Any Unicode character can be used (the whole Unicode 18.0 chart collection and anything later): the patcher never
rejects a letter because it does not know it. Whether the game can draw it depends on the Unicode settings and fonts.

## The public translations folder

Every accepted translation is in the repository's public [`translations/`](../translations/README.md) folder, one
file per language: `translations/<language code>.tsv` (`fr.tsv`, `pt-BR.tsv`), and `<code>-<credit>.tsv` when that
language already has a file (`fr-ann-lee.tsv`, then `fr-ann-lee-2.tsv`: ASCII, lower case, `a-z 0-9 -`, at most 40
letters; nothing is ever overwritten). The content is the same format as above (only the name and the `.tsv`
extension differ). The older `patcher/translations/vf1/*.txt` place is still read. A release ships every accepted
file except a "(TEST)" one (its language name or credit starts with "(TEST)", or its file name says it).
`translations/fr.tsv`, "(TEST) - French AI Translation" (credit "(TEST) AI translation"), is one: an AI translation of
every line, the game's and the patches', for trying out.

- **Download from GitHub...** (Translations window) lists that folder on the default branch with GitHub's read-only
  public API (only `api.github.com` and `raw.githubusercontent.com`, only this repository's `translations/`, no
  login, nothing about you sent): language, credit (shown in the name when a language has several files), the date
  it last changed, and **Update available** when your copy differs (GitHub's file SHA against your file's git blob
  SHA). Select one or more and press **Download**: each is checked as data (at most 2 MB, the validator, no email
  address) before it goes into `translations\vf1`. No network or GitHub's hourly limit is said plainly and changes
  nothing.
- **Uploading by hand:** the folder's README explains how to download a file, translate it, type a credit name, and
  upload it with GitHub's **Add file > Upload files** (a pull request is opened for you).
- **Checks on every pull request** (`.github/workflows/translations-check.yml`, `pull_request_target`, never
  checking out or running the pull request): the changed `translations/` files are fetched through the API as data
  (UTF-8 `.tsv` only, at most 2 MB), sent to **VirusTotal** first (`scripts/virustotal_scan.py`: looked up by
  SHA-256, uploaded and polled when unknown, at most 4 requests a minute), and only then validated with the base
  branch's validator (`scripts/translation_pr_check.py`); the result is commented on the pull request. Any engine
  that calls a file malicious or suspicious refuses it, naming the engines; VirusTotal unreachable, too slow, or the
  `VT_API_KEY` secret missing refuses it as "not scanned": nothing passes by default. Files sent to VirusTotal can
  be seen by VirusTotal's partners. Every push to main under `translations/` is scanned again
  (`translations-rescan.yml`).
- **The key:** the owner adds a VirusTotal API key as the repository secret `VT_API_KEY` (Settings > Secrets and
  variables > Actions). It is only passed to the one step that scans, never printed; without it every check fails
  and says the key is missing.

## Sharing

The Translations window says: "If you want to share your translation, consider going to the Patcher's GitHub page and
adding it!" -- How: press **Share on GitHub...**, drag the file in, press **Submit**.

Share on GitHub... first asks whether you want to continue (No is the default and changes nothing), then asks for the
**credit name** you want shown with the translation: you type it every time, it is public, and the patcher never fills
it in (not from git, Windows, GitHub or a save). **Email addresses are never saved and are rejected from translation
files.** Then the patcher writes a copy with that credit into `translations\Shared`, shows it in its folder and opens
GitHub's translation form with the game and language filled in: drag the file into the form and press Submit.

You need a free GitHub account: https://github.com/signup

When the owner accepts it (the `accept-translation` label), a GitHub Action downloads the file, scans it with
VirusTotal first (flagged or not scanned: refused, with a comment), downloads it again (it must be the scanned file),
checks it as data only with the patcher's own validator, and opens a pull request adding it to the public folder as
`translations/<language code>.tsv` (or `<code>-<credit>.tsv`), committed by the bot (github-actions[bot]) and
credited only to the typed credit name; if something is wrong it comments the problems instead. Accepted
translations ship in the next release, and anyone can download them at once with **Download from GitHub...**.

### Safety rules for names, replacing and checks

- **A check speaks for one commit.** The workflows cancel a stale run when a newer push or accept arrives (a
  concurrency group per pull request or issue). The accept action commits exactly the bytes VirusTotal scanned
  (SHA-256 compared before the commit) and reads the issue again just before pushing; if it changed, nothing is
  pushed. Any workflow that merges must use `gh pr merge --match-head-commit <checked sha>` (a test enforces it).
  No pull request code is ever checked out or run.
- **Names never collide with shipped files.** A translation you add never takes the name of one that came with the
  patcher or from GitHub (a new name gets "(2)"), **Edit...** on a shipped one makes your own copy
  ("... (own copy).txt"), and your remembered choice is stored as its source plus name (`vf1/fr.tsv`), so
  two files called `fr` cannot be confused. Old settings that hold only a name keep working.
- **Nothing is deleted for good.** A new file replaces an installed one only when the language, `@code` AND
  `@translator` all match (the same person's update); otherwise both are kept under different names. A replaced
  file goes to the Windows Recycle Bin (`SHFileOperationW` with `FOF_ALLOWUNDO`); if that fails nothing is replaced.
## For developers

- `patcher/translation_format.py`: the format (reading, writing, placeholders, person and number choices, CLDR plural
  rules, email refusal naming the line, coverage). Pure Python, no game or GUI imports: the Action runs it on a
  submitted file as data only.
- `patcher/vf1_translation_strings.py`: every line a translation can replace, with its room; read from the player's own
  executable (the patcher never ships the game's text).
- `patcher/vf1_translations.py`, `patcher/vf1_translations_window.py`: the files, the choice, sharing; the window and the
  editor (drag and drop through WM_DROPFILES).
- `native/vf1tr` builds `vf1tr.dll` (`native/build_tr.bat`). vf1fun.dll loads it last (after vf1text.dll / vf1font.dll)
  and calls `VF1Tr_Startup`. It passes a translation on as UTF-8 only when vf1text.dll or vf1font.dll answers
  `VF1Text_UnicodeTextActive()` (stdcall, nonzero only once all of that DLL's hooks are installed: the DLL installs all
  or nothing, so on an executable it did not match it is loaded but draws bytes); otherwise Windows-1252.
  **No code hook on the lookup:** the game's static string records `{id, key*, text*,
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
- `scripts/accept_translation.py` is the Action's check; `.github/ISSUE_TEMPLATE/translation.yml` the form;
  `scripts/virustotal_scan.py` the VirusTotal scan; `scripts/translation_pr_check.py` the pull request check;
  `patcher/vf1_translations_github.py` Download from GitHub....
- A line is a printf format when the game hands it to sprintf as the format (`"format"` in
  `data/vf1_translation_limits.json`) or vf1fun.dll hands it to swprintf (`"format"` in `data/vf1_patch_strings.json`,
  `native/vf1tr/vf1tr_patch_formats.h`); only those get a plain `%` written as `%%`.
- Tests: `tests/test_translation_format.py`, `tests/test_translations_runtime.py` (the DLL in Unicorn against the real
  game's GetString, template filler and guarded calls), `tests/test_translations_window.py`,
  `tests/test_translation_sharing.py`, `tests/test_patch_text_coverage.py`, `tests/test_virustotal_scan.py`,
  `tests/test_translation_pr_check.py`, `tests/test_translations_github.py`.
