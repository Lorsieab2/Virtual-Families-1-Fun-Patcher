"""Translation files, format version 1: the format every LDW patcher shares.

The Virtual Villagers Fun Patcher's docs/translation-file-format.md (v1, commit 7f3624bb) is
the specification; docs/translations.md here is the translator's guide. Ported from the Fish and
Plant Tycoon Fix Patcher (src/translation_format.py), with Virtual Families 1's own person choice
added (below). In short:

* one UTF-8 text file (written with a BOM; read with or without one, or as UTF-16 with a BOM)
  per game per language, named "<Game title> - <language's own name>.txt";
* a tab-separated table ``Key <TAB> English <TAB> Translation <TAB> Notes`` under a header row,
  ``#`` comment lines, and ``@format`` / ``@game`` / ``@language`` / ``@code`` /
  ``@translator`` information rows;
* ``\\n``, ``\\t`` and ``\\\\`` escapes inside a field; a field a spreadsheet wrapped in double
  quotes is unquoted;
* keys ``<source>/<id>~<first 8 hex digits of the SHA-256 of the English>``: a line whose
  English has changed since the file was made falls back to the new English;
* printf conversions (same ones, same order), ``{name}`` variables (any order) and selects
  ``{SUBJECT: key=text | key=text}`` with person keys ``m`` / ``f`` / ``o`` and number keys
  (the CLDR plural categories of the file's language, plus ``=N``);
* any bad row falls back to English and is reported; nothing ever raises out of ``parse``.

VIRTUAL FAMILIES 1.  The game fills some of its lines itself (theStringManager::
GetStringFromNameGenderTemplate 0x44FDD0): ``{name}`` and ``{name2}`` are family members' names,
``{award}`` a number, and ``{he/she}`` (``{his/her}``, ``{He/She}``...) is the game's own choice by
the first person's sex (``{a/2/b}`` by the second person's).  Those are variables and person choices
here: a translation keeps every variable and may use the game's form (``{il/elle}``) or the format's
(``{name: m=il | f=elle}``, ``{name2: ...}``) anywhere in such a line; vf1tr.dll writes either as the
game's ``{il/elle}``.  A line the game does not fill (it has no ``{...}`` in the English) cannot hold
a person choice.  Number choices (``{award: one=... | other=...}``) take their ``other`` branch in the
game: it never hands the count to the line.

This module is pure Python with no game or GUI imports, so the GitHub Action can run it on a
submitted file as data only. The runtime DLL (native/vf1tr) implements the same rules in C;
tests/test_translations_runtime.py checks the two agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import unicodedata

FORMAT_VERSION = 1
HEADER = ("Key", "English", "Translation", "Notes")
GAME_TITLES = {"vf1": "Virtual Families"}
ENGLISH_ORIGINAL = "English (original)"
INFO_KEYS = ("@format", "@game", "@language", "@code", "@translator")
# A spreadsheet or a phone keyboard may turn "@" into the full-width form; read both.
_AT_FORMS = ("@", "\uFF20")

EMAIL_MESSAGE = "Email addresses are never saved and are rejected from translation files."

KEY_RE = re.compile(r"^([a-z0-9_.-]+)/([A-Za-z0-9_./-]+)~([0-9a-f]{8})$")
# printf conversions: flags, width, precision, length, type. %n is recognised so it can be refused.
CONVERSION_RE = re.compile(
    r"%(?P<flags>[-+ #0]*)(?P<width>\d+|\*)?(?:\.(?P<precision>\d+|\*))?"
    r"(?P<length>hh|h|ll|l|L|I64|I32|I|w)?(?P<type>[diouxXcCsSfFeEgGaApn])"
)
NUMBER_TYPES = set("diouxX")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BRANCH_RE = re.compile(r"^(=[0-9]+|[A-Za-z]+)[ \t\n\r\f\v]*=(.*)$", re.DOTALL)
WS = " \t\n\r\f\v"     # the whitespace the runtime knows: ASCII only, so both strip alike
PERSON_KEYS = ("m", "f", "o")
PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")
# The game's own person choice inside a line it fills: {he/she} (the first person), {his/2/her} (the second).
NATIVE_CHOICE_RE = re.compile(r"^([^{}/|\\]*)/(?:(2)/)?([^{}/|\\]*)$")
# What Virtual Families 1 fills in a line (GetStringFromNameGenderTemplate): two people and a number.
DECLARED = {"name": "person", "name2": "person", "award": "number"}
# Anything that looks like an email address: an address (name, at sign, domain, dot, tld), with the full-width at sign, or
# the usual spelled-out disguises ("name [at] domain [dot] com").
_EMAIL_AT = r"(?:@|\uFF20|\s*[\(\[\{<]\s*at\s*[\)\]\}>]\s*)"
_EMAIL_DOT = r"(?:\.|\s*[\(\[\{<]\s*dot\s*[\)\]\}>]\s*)"
_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`|~.-]+"
EMAIL_RE = re.compile(
    # name, at sign, domain, dot, tld (also with the full-width at sign or "[at]" / "[dot]")
    _LOCAL + _EMAIL_AT + r"[A-Za-z0-9-]+(?:" + _EMAIL_DOT + r"[A-Za-z0-9-]+)*" + _EMAIL_DOT + r"[A-Za-z]{2,}"
    # "name at domain dot tld" (a plain "at" alone, as in "Try it at LDW.com", is not one)
    + r"|" + _LOCAL + r"\s+at\s+[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\s+dot\s+[A-Za-z]{2,}",
    re.IGNORECASE,
)


class TranslationError(ValueError):
    """A file that cannot be used at all (wrong encoding, game, format version, no header)."""


# --------------------------------------------------------------------------- small helpers


def key_hash(english: str) -> str:
    """The first 8 hex digits (lowercase) of the SHA-256 of the English, escapes decoded."""
    return hashlib.sha256(english.encode("utf-8")).hexdigest()[:8]


def make_key(source: str, ident: str, english: str) -> str:
    key = f"{source}/{ident}~{key_hash(english)}"
    if not KEY_RE.match(key):
        raise ValueError(f"not a valid key: {key!r}")
    return key


def split_key(key: str) -> tuple[str, str, str] | None:
    """(source, id, hash), or None for a malformed key."""
    match = KEY_RE.match(key)
    return (match.group(1), match.group(2), match.group(3)) if match else None


def base_key(key: str) -> str:
    """"<source>/<id>" of a key (the part that never changes)."""
    return key.rsplit("~", 1)[0]


def decode_escapes(text: str) -> str:
    """\\n, \\t and \\\\; any other backslash is kept as written."""
    if "\\" not in text:
        return text
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in "nt\\":
            out.append({"n": "\n", "t": "\t", "\\": "\\"}[text[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def encode_escapes(text: str) -> str:
    """The field form of a text: decode_escapes(encode_escapes(t)) == t for any t."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _unquote(field_text: str) -> str:
    """A spreadsheet's quoted field: "..." with "" for a quote."""
    if len(field_text) >= 2 and field_text.startswith('"') and field_text.endswith('"'):
        return field_text[1:-1].replace('""', '"')
    return field_text


def _quote(field_text: str) -> str:
    if field_text.startswith('"'):
        return '"' + field_text.replace('"', '""') + '"'
    return field_text


def decode_bytes(data: bytes) -> str:
    """UTF-8 with or without a BOM, or UTF-16 LE / BE with a BOM. Anything else raises."""
    if data.startswith(b"\xef\xbb\xbf"):
        body, codec = data[3:], "utf-8"
    elif data.startswith(b"\xff\xfe"):
        body, codec = data[2:], "utf-16-le"
    elif data.startswith(b"\xfe\xff"):
        body, codec = data[2:], "utf-16-be"
    else:
        body, codec = data, "utf-8"
    try:
        return body.decode(codec)
    except UnicodeDecodeError as exc:
        raise TranslationError(
            "The file is not UTF-8 (or UTF-16 with a byte-order mark). Save it as \"UTF-8\" or "
            f"\"Unicode Text\" and try again (byte {exc.start + (len(data) - len(body))} could not be read)."
        ) from None


def find_emails(text: str) -> list[str]:
    return [m.group(0) for m in EMAIL_RE.finditer(text)]


def contains_email(text: str) -> bool:
    return EMAIL_RE.search(text) is not None


def file_name(game_title: str, language: str) -> str:
    """"<Game title> - <language>.txt", with characters Windows cannot have in a name replaced."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", language).strip(" .") or "Translation"
    return f"{game_title} - {safe}.txt"


# --------------------------------------------------------------------------- plural rules

# CLDR plural rules for whole numbers (the games only count whole things). A language the
# program does not know uses English's. Each rule returns one of PLURAL_CATEGORIES; the
# native runtime (native/ftfp_translations/plural_rules.h) has the same table.


def _million_many(n: int) -> bool:
    return n != 0 and n % 1_000_000 == 0


def _rule_en(n):
    return "one" if n == 1 else "other"


def _rule_fr(n):
    if n in (0, 1):
        return "one"
    return "many" if _million_many(n) else "other"


def _rule_es(n):           # es, it, ca, pt-PT
    if n == 1:
        return "one"
    return "many" if _million_many(n) else "other"


def _rule_pt(n):           # pt, pt-BR
    if n in (0, 1):
        return "one"
    return "many" if _million_many(n) else "other"


def _rule_east_slavic(n):  # ru, uk, be
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def _rule_pl(n):
    if n == 1:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def _rule_cs(n):           # cs, sk
    if n == 1:
        return "one"
    return "few" if 2 <= n <= 4 else "other"


def _rule_south_slavic(n):  # hr, sr, bs
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "other"


def _rule_sl(n):
    if n % 100 == 1:
        return "one"
    if n % 100 == 2:
        return "two"
    return "few" if 3 <= n % 100 <= 4 else "other"


def _rule_lt(n):
    if n % 10 == 1 and not 11 <= n % 100 <= 19:
        return "one"
    if 2 <= n % 10 <= 9 and not 11 <= n % 100 <= 19:
        return "few"
    return "other"


def _rule_lv(n):
    if n % 10 == 0 or 11 <= n % 100 <= 19:
        return "zero"
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    return "other"


def _rule_ro(n):
    if n == 1:
        return "one"
    if n == 0 or 1 <= n % 100 <= 19:
        return "few"
    return "other"


def _rule_ar(n):
    if n == 0:
        return "zero"
    if n == 1:
        return "one"
    if n == 2:
        return "two"
    if 3 <= n % 100 <= 10:
        return "few"
    if 11 <= n % 100 <= 99:
        return "many"
    return "other"


def _rule_he(n):
    if n == 1:
        return "one"
    return "two" if n == 2 else "other"


def _rule_ga(n):
    if n == 1:
        return "one"
    if n == 2:
        return "two"
    if 3 <= n <= 6:
        return "few"
    return "many" if 7 <= n <= 10 else "other"


def _rule_cy(n):
    return {0: "zero", 1: "one", 2: "two", 3: "few", 6: "many"}.get(n, "other")


def _rule_none(_n):        # ja, zh, ko, vi, th, id, ms...
    return "other"


def _rule_zero_one(n):     # hi, bn, am, fa... (i = 0 or n = 1)
    return "one" if n in (0, 1) else "other"


def _rule_is(n):           # is, mk
    return "one" if n % 10 == 1 and n % 100 != 11 else "other"


def _rule_fil(n):
    return "one" if n in (1, 2, 3) or n % 10 not in (4, 6, 9) else "other"


PLURAL_RULES = {
    "en": _rule_en, "fr": _rule_fr, "es": _rule_es, "it": _rule_es, "ca": _rule_es, "pt": _rule_pt,
    "pt-pt": _rule_es, "ru": _rule_east_slavic, "uk": _rule_east_slavic, "be": _rule_east_slavic,
    "pl": _rule_pl, "cs": _rule_cs, "sk": _rule_cs, "hr": _rule_south_slavic, "sr": _rule_south_slavic,
    "bs": _rule_south_slavic, "sl": _rule_sl, "lt": _rule_lt, "lv": _rule_lv, "ro": _rule_ro,
    "mo": _rule_ro, "ar": _rule_ar, "he": _rule_he, "iw": _rule_he, "ga": _rule_ga, "cy": _rule_cy,
    "ja": _rule_none, "zh": _rule_none, "ko": _rule_none, "vi": _rule_none, "th": _rule_none,
    "id": _rule_none, "ms": _rule_none, "km": _rule_none, "lo": _rule_none, "my": _rule_none,
    "hi": _rule_zero_one, "bn": _rule_zero_one, "am": _rule_zero_one, "fa": _rule_zero_one,
    "gu": _rule_zero_one, "kn": _rule_zero_one, "mr": _rule_zero_one, "zu": _rule_zero_one,
    "is": _rule_is, "mk": _rule_is, "fil": _rule_fil, "tl": _rule_fil,
}
# The categories each rule can give (for "this language has no 'few' form" warnings).
_PROBE = list(range(0, 1200)) + [1_000_000, 2_000_000, 1_000_001]


def rule_for(code: str):
    code = (code or "").strip(WS).lower().replace("_", "-")
    if code in PLURAL_RULES:
        return PLURAL_RULES[code]
    primary = code.split("-", 1)[0]
    return PLURAL_RULES.get(primary, _rule_en)


def plural_category(code: str, n: int) -> str:
    return rule_for(code)(abs(int(n)))


def plural_categories(code: str) -> tuple[str, ...]:
    rule = rule_for(code)
    found = {rule(n) for n in _PROBE}
    return tuple(c for c in PLURAL_CATEGORIES if c in found)


# --------------------------------------------------------------------------- placeholders


@dataclass(frozen=True)
class Conversion:
    text: str            # as written, e.g. "%5.1f"
    type: str            # d, s, f...
    length: str          # "", "l", "I64"...
    stars: int           # "*" widths / precisions (each takes an argument)

    @property
    def signature(self) -> tuple[str, str, int]:
        """What must match between the English and the translation: the value's type, size and
        the arguments it takes. Flags, width and precision may change (%d -> %3d)."""
        kind = "d" if self.type == "i" else self.type
        return (kind, self.length, self.stars)

    @property
    def is_number(self) -> bool:
        return self.type in NUMBER_TYPES


@dataclass(frozen=True)
class Select:
    subject: str                         # "%1", "count"
    branches: tuple[tuple[str, str], ...]  # (key, text); text has its variables still in braces
    kind: str                            # "person" or "number"
    native: bool = False                 # the game's own {he/she} form


@dataclass
class Template:
    """A text broken into its placeholders."""
    conversions: list[Conversion] = field(default_factory=list)
    variables: set[str] = field(default_factory=set)
    selects: list[Select] = field(default_factory=list)
    lone_percent: bool = False
    errors: list[str] = field(default_factory=list)


def _parse_select_body(text: str, start: int, subject: str, template: Template) -> int:
    """Parse a select's branches from `start` (just after the ':') to its closing brace.
    Returns the index after the '}'; errors go to the template."""
    branches: list[tuple[str, str]] = []
    current: list[str] = []
    i = start
    closed = False
    while i < len(text):
        ch = text[i]
        if text.startswith("{{", i) or text.startswith("}}", i):
            current.append(text[i:i + 2])
            i += 2
            continue
        if ch == "\\" and i + 1 < len(text) and text[i + 1] == "|":
            current.append("\\|")
            i += 2
            continue
        if ch == "|":
            branches.append(("".join(current)))  # type: ignore[arg-type]
            current = []
            i += 1
            continue
        if ch == "}":
            branches.append(("".join(current)))  # type: ignore[arg-type]
            i += 1
            closed = True
            break
        if ch == "{":
            end = text.find("}", i + 1)
            inner = text[i + 1:end] if end != -1 else ""
            if end == -1:
                template.errors.append("a '{' inside a choice is never closed")
                return len(text)
            if ":" in inner:
                template.errors.append("a choice inside another choice; put each choice on its own")
                return len(text)
            if not NAME_RE.match(inner.strip(WS)):
                template.errors.append(f"'{{{inner}}}' inside a choice is not a variable name (write {{{{ for a brace)")
            else:
                template.variables.add(inner.strip(WS))
            current.append(text[i:end + 1])
            i = end + 1
            continue
        if ch == "%":
            if text.startswith("%%", i):
                current.append("%%")
                i += 2
                continue
            match = CONVERSION_RE.match(text, i)
            if match:
                template.errors.append(f"'{match.group(0)}' inside a choice; put the number outside the braces")
                current.append(match.group(0))
                i = match.end()
                continue
        current.append(ch)
        i += 1
    if not closed:
        template.errors.append(f"the choice {{{subject}: ...}} has no closing '}}'")
    parsed: list[tuple[str, str]] = []
    keys_seen = set()
    for raw in branches:
        match = BRANCH_RE.match(str(raw).strip(WS))
        if not match:
            template.errors.append(f"the choice {{{subject}: ...}} has a part without 'key=': {str(raw).strip(WS)!r}")
            continue
        key, value = match.group(1), match.group(2).strip(WS)
        if key in keys_seen:
            template.errors.append(f"the choice {{{subject}: ...}} has '{key}=' twice")
        keys_seen.add(key)
        parsed.append((key, value))
    if not parsed and closed:
        template.errors.append(f"the choice {{{subject}: ...}} is empty")
    person = all(k in PERSON_KEYS for k, _ in parsed)
    number = all(k in PLURAL_CATEGORIES or re.fullmatch(r"=[0-9]+", k) for k, _ in parsed)
    if parsed and not person and not number:
        bad = [k for k, _ in parsed if k not in PERSON_KEYS and k not in PLURAL_CATEGORIES
               and not re.fullmatch(r"=[0-9]+", k)]
        if bad:
            template.errors.append(
                f"the choice {{{subject}: ...}} has an unknown key {bad[0]!r} (people: m, f, o; numbers: "
                "zero, one, two, few, many, other, =0, =1...)")
        else:
            template.errors.append(f"the choice {{{subject}: ...}} mixes person keys (m, f, o) with number keys")
    kind = "person" if person and parsed else "number"
    template.selects.append(Select(subject, tuple(parsed), kind))
    return i


def parse_template(text: str) -> Template:
    """Split a text into its printf conversions, {variables} and {SUBJECT: ...} choices."""
    template = Template()
    i = 0
    while i < len(text):
        ch = text[i]
        if text.startswith("{{", i) or text.startswith("}}", i):
            i += 2
            continue
        if ch == "%":
            if text.startswith("%%", i):
                i += 2
                continue
            match = CONVERSION_RE.match(text, i)
            if match:
                conv = Conversion(match.group(0), match.group("type"), match.group("length") or "",
                                  (match.group("width") == "*") + (match.group("precision") == "*"))
                if conv.type == "n":
                    template.errors.append("'%n' is never allowed")
                template.conversions.append(conv)
                i = match.end()
                continue
            template.lone_percent = True
            i += 1
            continue
        if ch == "{":
            colon = text.find(":", i + 1)
            close = text.find("}", i + 1)
            if close == -1 and colon == -1:
                template.errors.append("a '{' is never closed (write {{ for a brace)")
                return template
            if close != -1 and (colon == -1 or close < colon):
                name = text[i + 1:close]
                native = NATIVE_CHOICE_RE.match(name)
                if NAME_RE.match(name.strip(WS)):
                    template.variables.add(name.strip(WS))
                elif native:
                    template.selects.append(Select("name2" if native.group(2) else "name",
                                                   (("m", native.group(1)), ("f", native.group(3))), "person",
                                                   native=True))
                else:
                    template.errors.append(f"'{{{name}}}' is not a variable name (write {{{{ and }}}} for braces)")
                i = close + 1
                continue
            subject = text[i + 1:colon].strip(WS)
            if not subject:
                template.errors.append("a choice has no subject before ':'")
            i = _parse_select_body(text, colon + 1, subject, template)
            continue
        if ch == "}":
            template.errors.append("a '}' that closes nothing (write }} for a brace)")
            i += 1
            continue
        i += 1
    return template


def subject_kind(subject: str, english: Template, declared: dict[str, str] | None = None) -> str | None:
    """"number", "person", "text" or None (unknown) for a choice's subject, from the English's
    conversions (%1 is its first) and the program's declared variables."""
    match = re.fullmatch(r"%([0-9]+)", subject)
    if match:
        index = int(match.group(1))
        if 1 <= index <= len(english.conversions):
            conv = english.conversions[index - 1]
            return "number" if conv.is_number else (declared or {}).get(subject, "text")
        return None
    return (declared or {}).get(subject)


def check_translation(english: str, translation: str, code: str = "en",
                      declared: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one translated line. Any error means the line shows English."""
    errors: list[str] = []
    warnings: list[str] = []
    if translation == "":
        return errors, warnings
    declared = DECLARED if declared is None else declared
    eng = parse_template(english)
    tra = parse_template(translation)
    errors.extend(tra.errors)
    if tra.lone_percent and not eng.lone_percent:
        errors.append("a '%' that is not a placeholder; write %% for a percent sign")
    a = [c.signature for c in eng.conversions]
    b = [c.signature for c in tra.conversions]
    if a != b:
        want = " ".join(c.text for c in eng.conversions) or "none"
        got = " ".join(c.text for c in tra.conversions) or "none"
        errors.append(f"the placeholders must be the same, in the same order: English has {want}, the "
                      f"translation has {got}")
    missing = sorted(eng.variables - tra.variables)
    extra = sorted(tra.variables - eng.variables)
    if missing:
        errors.append("missing " + ", ".join("{" + v + "}" for v in missing))
    if extra:
        errors.append(", ".join("{" + v + "}" for v in extra) + " is not in the English")
    categories = plural_categories(code)
    filled = bool(eng.variables or eng.selects)
    for select in tra.selects:
        if select.kind == "person" and select.subject in ("name", "name2"):
            if not filled:
                errors.append("this line is not one the game fills with a person's name, so a choice by person "
                              "({il/elle} or {name: m=... | f=...}) cannot be used in it")
                continue
            if any(c in value for _k, value in select.branches for c in "/{}"):
                errors.append("a choice by person cannot hold '/', '{' or '}' (the game splits it at '/')")
                continue
            if not select.native and not any(k in ("m", "f") for k, _v in select.branches):
                errors.append(f"the choice {{{select.subject}: ...}} needs m= and f= (the game knows male and female)")
                continue
        kind = subject_kind(select.subject, eng, declared)
        if kind is None:
            errors.append(f"the choice {{{select.subject}: ...}} chooses by something this line does not have "
                          f"(use %1, %2... for its placeholders)")
            continue
        if kind == "text":
            errors.append(f"{select.subject} is a text (a name), not a number or a person; a choice cannot use it")
            continue
        if kind != select.kind and select.branches:
            errors.append(f"{select.subject} is a {kind}; its choice needs "
                          + ("m=, f=, o=" if kind == "person" else "one=, other=... keys"))
            continue
        if kind == "number":
            for key, _value in select.branches:
                if key in PLURAL_CATEGORIES and key not in categories:
                    warnings.append(f"this language has no '{key}' form; that part of "
                                    f"{{{select.subject}: ...}} is never used")
    def edges(text: str) -> tuple[str, str]:
        return text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    if edges(english) != edges(translation):
        warnings.append("the spaces or line breaks at the start or end differ from the English")
    return errors, warnings


def evaluate(text: str, code: str = "en", numbers: dict[str, int] | None = None,
             sexes: dict[str, str] | None = None, longest: bool = False) -> str:
    """The text with every choice replaced by its branch and {{ }} made single.

    numbers / sexes give the subjects' values ("%1" -> 3, "%2" -> "f"); a subject with no value
    takes "o" (person) or "other" (number). Variables stay in braces for the caller."""
    numbers = numbers or {}
    sexes = sexes or {}
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("{{", i):
            out.append("{")
            i += 2
            continue
        if text.startswith("}}", i):
            out.append("}")
            i += 2
            continue
        ch = text[i]
        if ch == "{":
            colon = text.find(":", i + 1)
            close = text.find("}", i + 1)
            if close != -1 and (colon == -1 or close < colon):
                native = NATIVE_CHOICE_RE.match(text[i + 1:close])
                if native and not NAME_RE.match(text[i + 1:close].strip(WS)):
                    subject = "name2" if native.group(2) else "name"
                    m, f = native.group(1), native.group(3)
                    if longest:
                        out.append(max((m, f), key=lambda v: len(v.encode("utf-8"))))
                    else:
                        out.append(f if sexes.get(subject, "m") == "f" else m)
                else:
                    out.append(text[i:close + 1])
                i = close + 1
                continue
            if colon == -1:
                out.append(text[i:])
                break
            template = Template()
            subject = text[i + 1:colon].strip(WS)
            end = _parse_select_body(text, colon + 1, subject, template)
            select = template.selects[-1] if template.selects else None
            if select is not None and longest:
                out.append(max((_unescape_branch(v) for _k, v in select.branches),
                               key=lambda v: len(v.encode("utf-8")), default=""))
            elif select is not None:
                out.append(_unescape_branch(_choose(select, code, numbers, sexes)))
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _unescape_branch(text: str) -> str:
    return text.replace("\\|", "|").replace("{{", "{").replace("}}", "}")


def _choose(select: Select, code: str, numbers: dict, sexes: dict) -> str:
    branches = dict(select.branches)
    if not select.branches:
        return ""
    first = select.branches[0][1]
    if select.kind == "person":
        sex = sexes.get(select.subject, "o")
        return branches.get(sex, branches.get("o", branches.get("m", first)))
    value = numbers.get(select.subject)
    if value is None:
        return branches.get("other", first)
    exact = f"={abs(int(value))}"
    if exact in branches:
        return branches[exact]
    return branches.get(plural_category(code, value), branches.get("other", first))


# --------------------------------------------------------------------------- the file


@dataclass
class Row:
    line: int
    key: str
    english: str
    translation: str
    notes: str = ""
    extra: list[str] = field(default_factory=list)

    @property
    def is_info(self) -> bool:
        return self.key.startswith(_AT_FORMS)


@dataclass
class Problem:
    line: int                   # 1-based; 0 for the file as a whole
    severity: str               # "error" or "warning"
    message: str
    key: str = ""

    def __str__(self) -> str:
        where = f"Line {self.line}" if self.line else "File"
        return f"{where}: {self.severity}: {self.message}"


@dataclass
class TranslationFile:
    info: dict[str, tuple[str, str]] = field(default_factory=dict)   # "@code" -> (English, value)
    rows: list[Row] = field(default_factory=list)                    # the text rows, in file order
    items: list[tuple[str, object]] = field(default_factory=list)    # ("comment"|"blank"|"header"|"row", ...)
    problems: list[Problem] = field(default_factory=list)
    fatal: str = ""                                                  # why the whole file is unusable

    # ---- information rows
    def value(self, key: str) -> str:
        return self.info.get(key, ("", ""))[1]

    @property
    def language(self) -> str:
        return self.value("@language")

    @property
    def code(self) -> str:
        return self.value("@code") or "en"

    @property
    def translator(self) -> str:
        return self.value("@translator")

    @property
    def game(self) -> str:
        return self.info.get("@game", ("", ""))[0]

    def set_info(self, key: str, english: str, value: str) -> None:
        if key in self.info:
            for kind, item in self.items:
                if kind == "row" and isinstance(item, Row) and item.key == key:
                    item.english, item.translation = english, value
        else:
            row = Row(0, key, english, value)
            at = next((n + 1 for n, (k, _i) in enumerate(self.items) if k == "header"), len(self.items))
            last_info = [n for n, (k, i) in enumerate(self.items) if k == "row" and isinstance(i, Row) and i.is_info]
            if last_info:
                at = last_info[-1] + 1
            self.items.insert(at, ("row", row))
        self.info[key] = (english, value)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "warning"]

    def translations(self) -> dict[str, str]:
        """Key -> translation of every usable (error-free, translated) row."""
        bad = {p.key for p in self.problems if p.severity == "error" and p.key}
        return {r.key: r.translation for r in self.rows if r.translation and r.key not in bad}


def _info_key(key: str) -> str:
    return "@" + key[1:] if key.startswith("\uFF20") else key


def parse_text(text: str, game: str | None = None) -> TranslationFile:
    """Read a translation from its text. Never raises: problems are listed, and a file that
    cannot be used at all has `fatal` set (every row then shows English)."""
    tf = TranslationFile()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    header_seen = False
    seen_keys: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        if contains_email(line):
            tf.problems.append(Problem(number, "error", f"this line has an email address. {EMAIL_MESSAGE} "
                                                        "Remove it."))
        if line.strip() == "":
            tf.items.append(("blank", line))
            continue
        if line.startswith("#"):
            tf.items.append(("comment", line))
            continue
        columns = line.split("\t")
        if not header_seen:
            cells = [_unquote(c).strip(WS).lower() for c in columns[:3]]
            if cells == [h.lower() for h in HEADER[:3]]:
                header_seen = True
                tf.items.append(("header", line))
                continue
            tf.fatal = (f"Line {number}: the first row must be the header row "
                        "\"Key<TAB>English<TAB>Translation<TAB>Notes\"")
            tf.problems.append(Problem(number, "error", tf.fatal))
            break
        if len(columns) < 2:
            tf.problems.append(Problem(number, "error", "this row has no tab-separated columns (Key, English, "
                                                        "Translation, Notes); it is ignored"))
            tf.items.append(("bad", line))
            continue
        cells = [_unquote(c) for c in columns]
        key = cells[0].strip(WS)
        row = Row(number, _info_key(key), decode_escapes(cells[1]),
                  decode_escapes(cells[2]) if len(cells) > 2 else "",
                  cells[3] if len(cells) > 3 else "", cells[4:])
        tf.items.append(("row", row))
        if row.is_info:
            if row.key in tf.info:
                tf.problems.append(Problem(number, "warning", f"{row.key} is given twice; the first is used"))
                continue
            tf.info[row.key] = (row.english, row.translation)
            if row.key not in INFO_KEYS:
                tf.problems.append(Problem(number, "warning", f"unknown information row {row.key}; it is ignored"))
            continue
        tf.rows.append(row)
        parts = split_key(row.key)
        if parts is None:
            tf.problems.append(Problem(number, "error", f"the key {row.key!r} is not a valid key "
                                                        "(<source>/<id>~<8 hex digits>)", row.key))
            continue
        if row.key in seen_keys:
            tf.problems.append(Problem(number, "error", f"the key is already on line {seen_keys[row.key]}",
                                       row.key))
            continue
        seen_keys[row.key] = number
        if parts[2] != key_hash(row.english):
            tf.problems.append(Problem(number, "error", "the English column does not match the key (it must not "
                                                        "be edited); this line shows English", row.key))
            continue
    if not header_seen and not tf.fatal:
        tf.fatal = "the file has no header row \"Key<TAB>English<TAB>Translation<TAB>Notes\""
        tf.problems.append(Problem(0, "error", tf.fatal))
    if tf.fatal:
        return tf
    fmt = tf.value("@format") or tf.info.get("@format", ("", ""))[0]
    if not fmt:
        tf.problems.append(Problem(0, "warning", "no @format row; read as format 1"))
    else:
        major = fmt.strip(WS).split(".", 1)[0]
        if not major or not all(c in "0123456789" for c in major):
            tf.fatal = f"@format {fmt!r} is not a version number"
        elif int(major) > FORMAT_VERSION:
            tf.fatal = (f"the file is format {fmt}, newer than this patcher reads ({FORMAT_VERSION}); "
                        "update the patcher")
        if tf.fatal:
            tf.problems.append(Problem(0, "error", tf.fatal))
            return tf
    if game is not None:
        title = GAME_TITLES.get(game, game)
        if "@game" not in tf.info:
            tf.fatal = f"the file has no @game row; it must say {title}"
        elif tf.game.strip(WS) != title:
            tf.fatal = f"the file is for {tf.game.strip() or 'another game'!s}, not {title}"
        if tf.fatal:
            tf.problems.append(Problem(0, "error", tf.fatal))
            return tf
    if not tf.language.strip():
        tf.problems.append(Problem(0, "warning", "no @language row (the language's own name)"))
    code = tf.code
    for row in tf.rows:
        if any(p.key == row.key and p.severity == "error" for p in tf.problems):
            continue
        errors, warnings = check_translation(row.english, row.translation, code)
        for message in errors:
            tf.problems.append(Problem(row.line, "error", message + "; this line shows English", row.key))
        for message in warnings:
            tf.problems.append(Problem(row.line, "warning", message, row.key))
    return tf


def parse_bytes(data: bytes, game: str | None = None) -> TranslationFile:
    try:
        text = decode_bytes(data)
    except TranslationError as exc:
        tf = TranslationFile()
        tf.fatal = str(exc)
        tf.problems.append(Problem(0, "error", tf.fatal))
        return tf
    if text.startswith("\ufeff"):
        text = text[1:]
    return parse_text(text, game)


# --------------------------------------------------------------------------- writing


def to_text(tf: TranslationFile) -> str:
    out: list[str] = []
    header_written = False
    for kind, item in tf.items:
        if kind == "header":
            out.append("\t".join(HEADER))
            header_written = True
        elif kind == "row" and isinstance(item, Row):
            if not header_written:
                out.append("\t".join(HEADER))
                header_written = True
            cells = [item.key, encode_escapes(item.english), encode_escapes(item.translation)]
            if item.notes or item.extra:
                cells.append(item.notes)
            cells.extend(item.extra)
            out.append("\t".join(_quote(c) for c in cells))
        else:
            out.append(str(item))
    if not header_written:
        out.insert(0, "\t".join(HEADER))
    return "\r\n".join(out) + "\r\n"


def to_bytes(tf: TranslationFile) -> bytes:
    """UTF-8 with a byte-order mark and Windows line endings."""
    return b"\xef\xbb\xbf" + to_text(tf).encode("utf-8")


# --------------------------------------------------------------------------- templates and updates


@dataclass(frozen=True)
class Entry:
    """One line of a program's string inventory."""
    key: str
    english: str
    notes: str = ""
    max_length: int | None = None     # the translation may not be longer (see too_long)
    wide: bool = False                # counted in UTF-16 units (a Windows popup's text), not UTF-8 bytes


def new_file(game: str, entries: list[Entry], language: str, code: str, translator: str = "",
             comment: str | None = None) -> TranslationFile:
    """A fresh translation: every line with its English and notes, the translation empty."""
    title = GAME_TITLES.get(game, game)
    tf = TranslationFile()
    tf.items.append(("comment", comment or f"# {title} - {language} translation (format {FORMAT_VERSION}). "
                                          "Translate the third column; keep the Key and English as they are."))
    tf.items.append(("comment", "# docs/translations.md (Virtual Families 1 Fun Patcher) explains the format."))
    tf.items.append(("header", "\t".join(HEADER)))
    for key, english, value in (("@format", str(FORMAT_VERSION), str(FORMAT_VERSION)), ("@game", title, ""),
                                ("@language", "English", language), ("@code", "en", code),
                                ("@translator", "", translator)):
        row = Row(0, key, english, value)
        tf.items.append(("row", row))
        tf.info[key] = (english, value)
    for entry in entries:
        row = Row(0, entry.key, entry.english, "", entry.notes)
        tf.items.append(("row", row))
        tf.rows.append(row)
    return tf


@dataclass
class UpdateReport:
    added: list[str] = field(default_factory=list)          # new keys (untranslated)
    changed: list[str] = field(default_factory=list)        # new keys whose English changed
    unknown: list[str] = field(default_factory=list)        # keys the program no longer has


def update_to_inventory(tf: TranslationFile, entries: list[Entry]) -> UpdateReport:
    """Bring a translation up to the program's current lines, in place.

    Every current line is there afterwards, in the program's order, keeping its translation;
    a line whose English changed comes in untranslated, with the old line (and its translation)
    kept right after it for the translator to review; lines the program no longer has stay at
    the end (they are ignored)."""
    report = UpdateReport()
    by_key = {r.key: r for r in tf.rows}
    by_base: dict[str, list[Row]] = {}
    for r in tf.rows:
        by_base.setdefault(base_key(r.key), []).append(r)
    wanted = {e.key for e in entries}
    new_rows: list[Row] = []
    used: set[int] = set()
    for entry in entries:
        old = by_key.get(entry.key)
        if old is not None:
            if entry.notes and not old.notes:
                old.notes = entry.notes
            new_rows.append(old)
            used.add(id(old))
            continue
        row = Row(0, entry.key, entry.english, "", entry.notes)
        new_rows.append(row)
        stale = [r for r in by_base.get(base_key(entry.key), []) if r.key not in wanted and id(r) not in used]
        if stale:
            report.changed.append(entry.key)
            for r in stale:
                if r.translation:
                    new_rows.append(r)
                used.add(id(r))
        else:
            report.added.append(entry.key)
    for r in tf.rows:
        if id(r) not in used:
            report.unknown.append(r.key)
            new_rows.append(r)
    head = [(k, i) for k, i in tf.items if not (k == "row" and isinstance(i, Row) and not i.is_info)]
    tf.items = head + [("row", r) for r in new_rows]
    tf.rows = new_rows
    return report


@dataclass
class Report:
    """What Validate / Add translation file... tell the player."""
    file: TranslationFile
    total: int
    translated: int
    errors: list[Problem]
    warnings: list[Problem]
    english_changed: list[str]
    unknown: list[str]

    @property
    def coverage(self) -> float:
        return 100.0 * self.translated / self.total if self.total else 0.0

    @property
    def usable(self) -> bool:
        """The file can be installed and shared: it reads, is for this game, and has no email."""
        return not self.file.fatal and not any(EMAIL_MESSAGE in p.message for p in self.errors)

    def summary(self) -> str:
        lines = [f"Coverage: {self.translated} of {self.total} lines translated ({self.coverage:.1f}%)."]
        if self.file.fatal:
            lines.append("The file cannot be used: " + self.file.fatal)
        if self.errors:
            lines.append(f"{len(self.errors)} error(s) (those lines show English):")
            lines.extend("  " + str(p) for p in self.errors[:200])
        if self.english_changed:
            lines.append(f"{len(self.english_changed)} line(s) whose English has changed since the file was made "
                         "(they show the new English until translated again).")
        if self.unknown:
            lines.append(f"{len(self.unknown)} line(s) this version does not have (ignored).")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s):")
            lines.extend("  " + str(p) for p in self.warnings[:200])
        return "\n".join(lines)


def validate(tf: TranslationFile, entries: list[Entry] | None = None) -> Report:
    """Coverage, errors and warnings; against the program's inventory when given."""
    errors = list(tf.errors)
    warnings = list(tf.warnings)
    changed: list[str] = []
    unknown: list[str] = []
    bad = {p.key for p in errors if p.key}
    if entries is None:
        total = len(tf.rows)
        translated = sum(1 for r in tf.rows if r.translation and r.key not in bad)
        return Report(tf, total, translated, errors, warnings, changed, unknown)
    known = {e.key: e for e in entries}
    bases = {base_key(e.key) for e in entries}
    translated = 0
    for row in tf.rows:
        if row.key in known:
            entry = known[row.key]
            if row.translation and row.key not in bad:
                if entry.max_length is not None and too_long(row.translation, entry.max_length, entry.wide):
                    errors.append(Problem(row.line, "error", too_long_message(entry.max_length), row.key))
                else:
                    translated += 1
        elif split_key(row.key) and base_key(row.key) in bases:
            changed.append(row.key)
            if row.translation:
                warnings.append(Problem(row.line, "warning", "the English has changed since this line was "
                                                             "translated; it shows the new English", row.key))
        elif split_key(row.key):
            unknown.append(row.key)
            errors.append(Problem(row.line, "error", "this version has no such line (unknown key); it is "
                                                     "ignored", row.key))
    return Report(tf, len(entries), translated, errors, warnings, changed, unknown)


def game_text(translation: str) -> str:
    """The translation as vf1tr.dll hands it to the game: a person choice in the game's own form
    ({il/elle}, {il/2/elle}), a number choice at its other branch, {{ }} made single."""
    out: list[str] = []
    i = 0
    text = translation
    while i < len(text):
        if text.startswith("{{", i) or text.startswith("}}", i):
            out.append(text[i])
            i += 2
            continue
        if text[i] == "{":
            colon, close = text.find(":", i + 1), text.find("}", i + 1)
            if close != -1 and (colon == -1 or close < colon):
                out.append(text[i:close + 1])
                i = close + 1
                continue
            if colon == -1:
                out.append(text[i:])
                break
            template = Template()
            subject = text[i + 1:colon].strip(WS)
            end = _parse_select_body(text, colon + 1, subject, template)
            select = template.selects[-1] if template.selects else None
            if select is not None and select.kind == "person" and subject in ("name", "name2"):
                branches = dict(select.branches)
                pick = lambda k: _unescape_branch(branches.get(k, branches.get("o", select.branches[0][1] if select.branches else "")))  # noqa: E731
                out.append("{" + pick("m") + ("/2/" if subject == "name2" else "/") + pick("f") + "}")
            elif select is not None:
                out.append(_unescape_branch(_choose(select, "en", {}, {})))
            i = end
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def measure(translation: str, wide: bool = False) -> int:
    """A translation's size as the runtime measures it: the larger of each choice at its longest
    branch and the text the game is handed (game_text), in UTF-8 bytes (UTF-16 units if wide)."""
    sizes = []
    for text in (evaluate(translation, longest=True), game_text(translation)):
        sizes.append(len(text.encode("utf-16-le")) // 2 if wide else len(text.encode("utf-8")))
    return max(sizes)


def too_long(translation: str, max_length: int, wide: bool = False) -> bool:
    """Past a line's room (measure): a letter with an accent counts 2 in UTF-8."""
    return measure(translation, wide) > max_length


def too_long_message(max_length: int) -> str:
    return (f"too long: this line has room for {max_length} letters (an accented or non-Latin letter "
            "counts as 2 or more); it shows English")


def normalise_credit(name: str) -> str:
    """A credit name as typed, made safe for one line of the file."""
    name = unicodedata.normalize("NFC", name).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return " ".join(name.split())
