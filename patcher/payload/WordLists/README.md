# Shared word lists for word breaking (Thai, Lao, Khmer, Burmese, Chinese, Japanese)

One set of word lists for ALL four patchers (Fish/Plant, Virtual Families 1 and 2, Virtual Villagers),
so they break text identically. These languages are written without spaces between words, so a line
break can only be placed well with a word list. Korean, Arabic, Hebrew, Hindi and the other widely
used scripts put spaces between words and need no list.

## Source

- Project: ICU (International Components for Unicode), https://github.com/unicode-org/icu
- Version: tag `release-77-1`, commit `457157a92aa053e632cc7fcfd0e12f8a943b2d11`
- Path in the repo: `icu4c/source/data/brkitr/dictionaries/<name>`
- Downloaded 2026-11-03 from `https://raw.githubusercontent.com/unicode-org/icu/release-77-1/...` as data only.
- Licence: `ICU-LICENSE.txt` (the repository's root `LICENSE`, 26,487 bytes, UNICODE LICENSE V3 plus the
  third-party notices for these lists: IPADIC and BSD for the Chinese/Japanese list, the Lao list and the
  Myanmar Karen word lists). It MUST ship in the release next to the lists (a credits line in the README
  is not enough on its own).

## Files

| File | Language | Bytes | SHA-256 | Origin |
| --- | --- | ---: | --- | --- |
| `thaidict.txt` | Thai | 493,054 | `3166abde40c0f44ab91c28f5ce96d7d1472cb7882e1c0bda0a72f8f69dba4274` | ICU's Thai dictionary (IBM and others, under the Unicode licence) |
| `laodict.txt` | Lao | 673,894 | `3c876934a3fa81031d2333525eafaca6a7c9f842e3b98f18c38880420afb5d36` | Lao word list by Brian Eugene Wilson and Robert Martin Campbell (github.com/rober42539/lao-dictionary) |
| `khmerdict.txt` | Khmer | 2,031,114 | `87bee2d17cd5148aa36957eb05409eefc124de8ad519b81b789298ef3e60b5d9` | ICU's Khmer dictionary (IBM and others, under the Unicode licence) |
| `burmesedict.txt` | Burmese (Myanmar) | 1,164,408 | `61d8abc3d9102b2f9bf0c9f44db0d7ab89b18172d8cd26832e4c83174bd8673b` | Myanmar Karen Word Lists (github.com/kanyawtech/myanmar-karen-word-lists) and ICU |
| `cjdict.txt` | Chinese and Japanese | 4,195,904 | `e73fd72048981d0cc13e9dc436a7eaba07ffb6eff58c8a59dc75c1df746663a0` | Libtabe (Chinese) and IPADIC (Japanese), combined and trained by ICU, with word frequencies |
| `ICU-LICENSE.txt` | the licence | 26,487 | `451167c55c0fa447cc2d5632714f5e3c567fe4f1e1badefab2c1333852198aca` | ICU root LICENSE |

Total 8,558,374 bytes (8.2 MiB) as text; 2,464,550 bytes (2.4 MiB) zipped.

## Format

UTF-8 text with a byte order mark; `#` lines are comments; one word per line. `cjdict.txt` lines are
`word<TAB>frequency`. Match case exactly as written (these scripts have no case).

## How the patchers use them

1. First choice: Windows' own `icu.dll` break iterator (Windows 10 and later has it, with these same
   dictionaries built in): `ubrk_open(UBRK_LINE, ...)`. No list is needed then.
2. Fallback (older Windows, or the patcher's editor): longest-match segmentation with these lists, then
   the usual UAX #14 rules between the words (kinsoku, never inside a grapheme cluster).
3. Load the lists lazily, only when text in one of these scripts is seen, and keep them out of the game's
   process unless a translation actually needs them (about 8.5 MB as text).

## Rules for every repo

- Copy the whole folder unchanged (same bytes, so the SHA-256 values above still match); a test should
  check each file's SHA-256 against this table.
- Never edit a list. If a word is missing, add it in a separate small `extra-words.txt`.
- Keep `ICU-LICENSE.txt` in the release and credit ICU, the Lao word list, the Myanmar Karen word lists,
  Libtabe and IPADIC in the README credits.
- To update to a newer ICU, change this folder once and tell every repo.
