# Translations

This is the public folder of Virtual Families 1 translations. Everyone can download them, use them in the game and
add new ones. The patcher's **Translations** window (Tools tab) can download them for you with
**Download from GitHub...**.

Each file is one language, named after its language code: `fr.tsv`, `de.tsv`, `pt-BR.tsv`... When a language
already has a file, another translator's file gets their credit name after the code (`fr-ann-lee.tsv`,
`fr-ann-lee-2.tsv`), so nothing is ever overwritten.

## Use a translation in the game

- **With the patcher:** Tools tab, **Translations...**, **Download from GitHub...**. Pick one or more files and
  press **Download**. Then choose the language under **Language in the game**.
- **By hand:** open the file here, press the **Download raw file** button, and in the patcher's Translations window
  press **Add translation file...** (or drag the file onto that window).

## Make or improve a translation

1. **Download** a file from this folder (open it, then **Download raw file**), or make a new one in the patcher:
   Tools tab, **Translations...**, **Make a translation...**.
2. **Translate** it in the patcher's built-in editor (the English on the left, your translation on the right; it
   checks every line as you type), or in any text editor: it is plain UTF-8 text with tab-separated columns
   **Key**, **English**, **Translation**, **Notes**. Only fill in the **Translation** column. A spreadsheet works too
   if you open and save it as tab-separated text.
3. **Type your credit name** in the `@translator` row, in its **Translation** column (the third column), for example
   `@translator` *tab* *tab* `Ann Lee`. That name is public and is shown with your translation. Use a name or a
   nickname, never an email address.
4. **Upload** it here: on this folder's page press **Add file**, then **Upload files**, drag your file in (name it
   `<language code>.tsv`, for example `fr.tsv`, or `fr-<your name>.tsv` if that language is already here), write a
   short description and press **Propose changes**. If you cannot write to this repository (most people), GitHub
   makes a copy for you and opens a pull request automatically. You need a free GitHub account:
   https://github.com/signup

You can also press **Share on GitHub...** in the patcher's Translations window: it asks the same questions and
opens a form for you; the owner then adds the file here.

Please DO NOT put ANY PRIVATE DETAILS YOU DO NOT WANT TO MAKE PUBLIC!

Email addresses are never saved and are rejected from translation files.

## What happens to an uploaded file

Every file in a pull request is checked automatically before the owner looks at it:

- **VirusTotal:** each submitted file is sent to VirusTotal (virustotal.com) to be scanned for anything harmful. Files
  sent to VirusTotal can be seen by VirusTotal's partners (security companies), so only upload what you are happy to
  make public. Anything VirusTotal flags is rejected, and a file that could not be scanned is not accepted either.
- **The patcher's own validator:** the file is read as text only (nothing in it is ever run) and every line is
  checked: the format, the keys, the placeholders (`{name}`, `%d`) and choices, and email addresses (refused, with
  the line named). The result is written as a comment on the pull request.

Only `.tsv` files of at most 2 MB, in UTF-8, directly in this folder, are accepted.

The full guide to the file format is in [docs/translations.md](../docs/translations.md).
