"""The patcher's side of translations: where they live, which one the game uses, installing,
exporting and sharing. The window is vf1_translations_window.py; the format is translation_format.py;
the lines are vf1_translation_strings.py; the game side is vf1tr.dll (native/vf1tr). Ported from the
Fish and Plant Tycoon Fix Patcher (src/translations.py).

* Every translation lives in the patcher's "translations" folder, one flat folder of
  "Virtual Families - <language>.txt" files; the ones that came with the patcher (accepted on GitHub)
  are in its "vf1" subfolder. Only the English template is ever generated.
* The choice is remembered in "translation_choice.json" beside the patcher and written into every
  modded copy of the game the patcher knows: "<copy>\\Virtual Families 1 Patcher Files\\Translation.ini"
  (language=, file=<full path>) and a copy of the file, Translation.txt, beside it (used when the
  patcher folder has moved). vf1tr.dll reads them at the next game start: no re-patching.
* Nothing here ever stores or sends an email address: the credit name is typed by the player, and
  any email-like text is refused (translation_format.EMAIL_RE).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import urllib.parse

import translation_format as tfmt

HERE = Path(__file__).resolve().parent
TRANSLATIONS_DIR = HERE / "translations"
CHOICE_PATH = HERE / "translation_choice.json"
GAME_IDS = ("vf1",)
DLL_FOLDERS = {"vf1": "Virtual Families 1 Patcher Files"}
DLL_NAME = "vf1tr.dll"
INI_NAME = "Translation.ini"
COPY_NAME = "Translation.txt"
REPOSITORY = "https://github.com/Lorsieab2/Virtual-Families-1-Fun-Patcher"
ISSUE_URL = REPOSITORY + "/issues/new"
ISSUE_TEMPLATE = "translation.yml"
SIGNUP_URL = "https://github.com/signup"
MAX_FILE = 8 * 1024 * 1024
CREDIT_MAX = 60

# The owner's wording, exactly (the Share on GitHub... confirmation).
SHARE_CONFIRMATION = (
    "This button allows you to share your game translation to the patcher's Public Github. IF ACCEPTED, "
    "everyone who uses this patcher will be able to see your translation in the game and your username will "
    "be included in the credits. Please DO NOT put ANY PRIVATE DETAILS YOU DO NOT WANT TO MAKE PUBLIC!\n\n"
    "Email addresses are never saved and are rejected from translation files.\n\n"
    "This feature is meant to be a community collaboration tool for game modding only.\n\n"
    "You will need a Github account to proceed. Continue?"
)
SHARE_INVITE = ("If you want to share your translation, consider going to the Patcher's GitHub page and "
                "adding it!")
SHARE_HOW = "How: press Share on GitHub..., drag the file in, press Submit."
CREDIT_HINT = ("The name shown in the credits, typed by you. It is public. "
               + tfmt.EMAIL_MESSAGE)

# Languages offered by "Make a translation" (their own names, BCP 47 codes); "Other..." adds any.
LANGUAGES = (
    ("Français", "fr"), ("Deutsch", "de"), ("Español", "es"), ("Italiano", "it"), ("Português (Brasil)", "pt-BR"),
    ("Português (Portugal)", "pt-PT"), ("Nederlands", "nl"), ("Polski", "pl"), ("Türkçe", "tr"), ("Русский", "ru"),
    ("Українська", "uk"), ("日本語", "ja"), ("简体中文", "zh-Hans"), ("繁體中文", "zh-Hant"), ("한국어", "ko"),
    ("Svenska", "sv"), ("Norsk bokmål", "nb"), ("Dansk", "da"), ("Suomi", "fi"), ("Čeština", "cs"),
    ("Slovenčina", "sk"), ("Magyar", "hu"), ("Română", "ro"), ("Ελληνικά", "el"), ("עברית", "he"),
    ("العربية", "ar"), ("हिन्दी", "hi"), ("Bahasa Indonesia", "id"), ("Tiếng Việt", "vi"), ("ไทย", "th"),
    ("Català", "ca"), ("Hrvatski", "hr"), ("Srpski", "sr"), ("Български", "bg"), ("Lietuvių", "lt"),
    ("Latviešu", "lv"), ("Eesti", "et"), ("Slovenščina", "sl"), ("Filipino", "fil"), ("Esperanto", "eo"),
)


class TranslationProblem(Exception):
    """Something the player must hear about (shown as is)."""


# --------------------------------------------------------------------------- installed files


@dataclass
class Installed:
    path: Path
    game: str
    language: str
    code: str
    translator: str
    shipped: bool                     # came with the patcher (translations/<game>/)

    @property
    def label(self) -> str:
        """Its name in the language list: the language, and who made it."""
        name = self.language or self.path.stem.split(" - ", 1)[-1]
        if self.translator:
            name += f" (by {self.translator})"
        return name


def read_info(path: Path, game: str) -> Installed | None:
    """An installed translation for this game, or None (another game, unreadable)."""
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        parsed = tfmt.parse_bytes(path.read_bytes(), game)
    except OSError:
        return None
    if parsed.fatal:
        return None
    translator = parsed.translator if not tfmt.contains_email(parsed.translator) else ""
    shipped = path.parent.name.lower() == game
    return Installed(path, game, parsed.language.strip(), parsed.code.strip(), translator.strip(), shipped)


def installed(game: str, folder: Path | None = None) -> list[Installed]:
    """Every translation for this game: the ones that came with the patcher, then the player's."""
    folder = folder or TRANSLATIONS_DIR
    found: list[Installed] = []
    for path in sorted(list((folder / game).glob("*.txt")) + list(folder.glob("*.txt"))):
        info = read_info(path, game)
        if info is not None:
            found.append(info)
    found.sort(key=lambda i: (not i.shipped, i.label.casefold()))
    return found


def install_file(source: Path, game: str, entries: list[tfmt.Entry] | None = None,
                 folder: Path | None = None) -> tuple[Path, tfmt.Report]:
    """Validate a translation file and copy it into the translations folder under its proper name.
    Raises TranslationProblem (with the report) when it cannot be used at all or has an email."""
    folder = folder or TRANSLATIONS_DIR
    try:
        if source.stat().st_size > MAX_FILE:
            raise TranslationProblem(f"The file is too big ({source.stat().st_size} bytes) to be a translation.")
        data = source.read_bytes()
    except OSError as exc:
        raise TranslationProblem(f"Could not read the file: {exc.strerror or exc}") from None
    parsed = tfmt.parse_bytes(data, game)
    report = tfmt.validate(parsed, entries)
    if parsed.fatal:
        raise TranslationProblem("This file cannot be used: " + parsed.fatal)
    if not report.usable:
        raise TranslationProblem("This file has an email address. " + tfmt.EMAIL_MESSAGE + "\n\n" + report.summary())
    language = parsed.language.strip() or source.stem.split(" - ", 1)[-1]
    target = folder / tfmt.file_name(tfmt.GAME_TITLES[game], language)
    folder.mkdir(parents=True, exist_ok=True)
    if target.resolve() != source.resolve():
        shutil.copyfile(source, target)
    return target, report


def export_file(source: Path, destination: Path) -> Path:
    shutil.copyfile(source, destination)
    return destination


# --------------------------------------------------------------------------- the choice


def load_choices(path: Path | None = None) -> dict[str, str]:
    """game -> the chosen file (a path relative to the translations folder), "" for English."""
    try:
        data = json.loads((path or CHOICE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {g: str(data.get(g, "")) for g in GAME_IDS if isinstance(data, dict)}


def save_choices(choices: dict[str, str], path: Path | None = None) -> None:
    (path or CHOICE_PATH).write_text(json.dumps({g: choices.get(g, "") for g in GAME_IDS}, indent=2) + "\n",
                                     encoding="utf-8")


def chosen_path(game: str, choices: dict[str, str] | None = None, folder: Path | None = None) -> Path | None:
    name = (choices if choices is not None else load_choices()).get(game, "")
    if not name:
        return None
    path = (folder or TRANSLATIONS_DIR) / name
    return path if path.is_file() else None


def relative_name(path: Path, folder: Path | None = None) -> str:
    folder = folder or TRANSLATIONS_DIR
    try:
        return path.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return path.name


def write_choice(game_copy: Path, game: str, translation: Path | None, language: str = "") -> bool:
    """Tell one copy of the game which translation to use (None: English). Returns False when the
    copy has no vf1tr.dll (patched without the Translations setting) or cannot be written."""
    dll_folder = Path(game_copy) / DLL_FOLDERS[game]
    if not (dll_folder / DLL_NAME).is_file():
        return False
    try:
        ini = dll_folder / INI_NAME
        copy = dll_folder / COPY_NAME
        if translation is None:
            for path in (ini, copy):
                if path.exists():
                    path.unlink()
            return True
        text = ("; Written by the Virtual Families 1 Fun Patcher's Translations window. vf1tr.dll reads\r\n"
                "; it when the game starts. Change it there (Tools tab, Translations...).\r\n"
                f"language={language}\r\nfile={Path(translation).resolve()}\r\n")
        ini.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        shutil.copyfile(translation, copy)
        return True
    except OSError:
        return False


def write_choice_into(game_copy: Path, game: str) -> bool:
    """At patch time: the new copy uses the language chosen for this game (if any)."""
    path = chosen_path(game)
    info = read_info(path, game) if path is not None else None
    return write_choice(game_copy, game, path if info else None, info.language if info else "")


def game_copies(game: str, folders) -> list[Path]:
    """The modded copies of the game the patcher knows of (the given folders and the folders beside
    them) that have vf1tr.dll."""
    title = tfmt.GAME_TITLES[game]
    seen: list[Path] = []
    candidates: list[Path] = []
    for folder in folders:
        if not folder or not str(folder).strip():
            continue
        folder = Path(str(folder).strip().strip('"'))
        candidates.append(folder)
        for parent in (folder, folder.parent):
            for name in (f"{title} - Modded",):
                candidates.append(parent / name)
    for folder in candidates:
        try:
            if (folder / DLL_FOLDERS[game] / DLL_NAME).is_file() and folder.resolve() not in seen:
                seen.append(folder.resolve())
        except OSError:
            continue
    return seen


def apply_choice(game: str, translation: Path | None, folders, choices_path: Path | None = None,
                 translations_folder: Path | None = None) -> list[Path]:
    """Choose a translation for a game (None: English (original)): remember it and write it into
    every known copy. Returns the copies written."""
    choices = load_choices(choices_path)
    choices[game] = relative_name(translation, translations_folder) if translation is not None else ""
    save_choices(choices, choices_path)
    language = ""
    if translation is not None:
        info = read_info(translation, game)
        language = info.language if info else ""
    return [copy for copy in game_copies(game, folders) if write_choice(copy, game, translation, language)]


# --------------------------------------------------------------------------- sharing


def check_credit_name(name: str) -> str:
    """The credit name to use, or raise TranslationProblem. Required, typed by the player."""
    name = tfmt.normalise_credit(name or "")
    if not name:
        raise TranslationProblem("Please type the name you want in the credits (it is required).")
    if tfmt.contains_email(name) or "@" in name or "＠" in name:
        raise TranslationProblem("The credit name looks like an email address. " + tfmt.EMAIL_MESSAGE)
    if len(name) > CREDIT_MAX:
        raise TranslationProblem(f"Please keep the credit name to {CREDIT_MAX} letters.")
    return name


def issue_url(game: str, language: str, coverage: float | None = None) -> str:
    """GitHub's new-issue page with the translation form, the game and language filled in.
    Nothing personal goes in the address."""
    params = {
        "template": ISSUE_TEMPLATE,
        "title": f"Translation: {tfmt.GAME_TITLES[game]} - {language}",
        "game": tfmt.GAME_TITLES[game],
        "language": language,
        "labels": "translation",
    }
    if coverage is not None:
        params["coverage"] = f"{coverage:.0f}%"
    return ISSUE_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def set_credit(path: Path, name: str) -> None:
    """Write the credit name into a translation's @translator row (the file stays as it is otherwise)."""
    name = check_credit_name(name)
    parsed = tfmt.parse_bytes(path.read_bytes())
    if parsed.fatal:
        raise TranslationProblem("This file cannot be used: " + parsed.fatal)
    parsed.set_info("@translator", "", name)
    path.write_bytes(tfmt.to_bytes(parsed))
